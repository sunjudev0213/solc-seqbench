# Execute whole rules in one shell invocation (instead a separete shell for every line) and fail on first error
.ONESHELL:
.SHELLFLAGS += -euo pipefail

.SECONDEXPANSION:
percent := %

sequences := $(basename $(notdir $(wildcard input/sequences/*.txt)))
contracts := $(basename $(notdir $(wildcard input/contracts/*.json)))
calls     := \
    $(foreach contract, $(contracts), \
        $(addprefix $(contract)/, \
            $(basename $(notdir $(wildcard input/calls/$(contract)/*.txt))) \
        ) \
    )

all_sequence_info_json := \
    $(foreach sequence, $(sequences), \
        $(foreach contract, $(contracts), \
            output/optimization/$(sequence)/$(contract)-sequence-info.json \
        ) \
    )

all_sequence_contract_json := \
    $(foreach sequence, $(sequences), \
        $(foreach contract, $(contracts), \
            output/optimization/$(sequence)/$(contract).json \
        ) \
    )

all_sequence_call_json := \
    $(foreach sequence, $(sequences), \
        $(foreach call, $(calls), \
            output/execution/$(sequence)/$(call).json \
        ) \
    )

all_sequence_call_reports_json := \
    $(foreach sequence, $(sequences), \
        $(foreach call, $(calls), \
            output/analysis/$(sequence)/$(call)/report.json \
        ) \
    )

# Convenience targets for selecting specific contracts/sequences
all_sequence_targets := $(foreach sequence, $(sequences), sequence-$(sequence))
all_contract_targets := $(foreach contract, $(contracts), contract-$(contract))
all_sequence_contract_targets := \
    $(foreach sequence, $(sequences), \
        $(foreach contract, $(contracts), \
            sequence-$(sequence)/contract-$(contract) \
        ) \
    )

.PHONY: \
    all \
    clean \
    unoptimized-ir \
    $(all_sequence_targets) \
    $(all_contract_targets) \
    $(all_sequence_contract_targets)

all: \
    output/optimization.json \
    output/execution.json \
    $(all_sequence_targets)

unoptimized-ir: $(foreach c, $(contracts), output/contracts/$(c).yul)

solidity/: solc-sequence-info-dump.patch
	branch="fix-superfluous-iterations-in-optimizer-sequence"

	git clone https://github.com/ethereum/solidity --branch "$$branch" --depth 1
	cd solidity/
	git apply --verbose ../solc-sequence-info-dump.patch

solc: solidity/
	export CMAKE_OPTIONS="-DUSE_Z3=OFF -DUSE_CVC4=OFF -DSOLC_STATIC_STDLIBS=ON"
	# TODO: Build only solc, without other executables
	solidity/scripts/ci/build.sh seqbench
	strip solidity/build/solc/solc

	mv solidity/build/solc/solc .
	chmod +x solc

output/contracts/:
	mkdir -p "$(dir $@)"

output/contracts/%.json: input/contracts/%.json | output/contracts/
	cd input/contracts/
	solc --standard-json "$(notdir $<)" --allow-paths ../sources/ --pretty-json --json-indent 4 > "../../$@"

	errors=$$(jq '.errors[] | select(.type == "Error")' --indent 4 "../../$@")
	[[ $$errors == "" ]] || { >&2 echo "$$errors"; false; }

output/contracts/%.yul: output/contracts/%.json
	jq --raw-output '.contracts | to_entries[0].value | to_entries[0].value.ir' --indent 4 "$<" > "$@" || { >&2 cat "$<"; false; }

$(all_sequence_info_json): \
    output/optimization/%-sequence-info.json: \
    output/contracts/$$(word 2, $$(subst /, , $$*)).yul \
    input/sequences/$$(word 1, $$(subst /, , $$*)).txt

	sequence_name="$(word 1, $(subst /, , $*))"
	contract_name="$(word 2, $(subst /, , $*))"

	# Load sequence but strip comments from line ends and remove empty lines
	sequence=$$(sed -e 's|^\([^#]*\).*$$|\1|g' -e '/^\s*$$/d' "input/sequences/$${sequence_name}.txt")

	# Run patched solc that can dump internal information about the sequence, including which steps
	# actually run and timing info of the optimization alone.
	output_dir="output/optimization/$${sequence_name}/$${contract_name}/"
	export SOLC_DUMP_SEQUENCE_INFO=1
	./solc --strict-assembly "$<" --optimize --yul-optimizations "$$sequence" --ir-optimized > /dev/null
	mkdir -p "$(dir $@)"
	mv sequence-info.json "$@"

$(all_sequence_contract_json): \
    output/optimization/%.json: \
    output/contracts/$$(word 2, $$(subst /, , $$*)).yul \
    input/sequences/$$(word 1, $$(subst /, , $$*)).txt \
    output/optimization/$$(word 1, $$(subst /, , $$*))/$$(word 2, $$(subst /, , $$*))-sequence-info.json \
    assemble-all-steps.py

	sequence_name="$(word 1, $(subst /, , $*))"
	contract_name="$(word 2, $(subst /, , $*))"
	sequence_info_file="output/optimization/$${sequence_name}/$${contract_name}-sequence-info.json"
	flattened_sequence=$$(jq '.[0].flattened_sequence_no_hardcoded' "$$sequence_info_file" --raw-output)

	# Generate a .json file for each step, containing info about compilation.
	# For those steps that did not fail with StackTooDeep error, a .yul file is also generated.
	output_dir="output/optimization/$${sequence_name}/$${contract_name}/"
	rm -rf "./$${output_dir}/"
	./assemble-all-steps.py "$<" "$$flattened_sequence" --output-dir "$$output_dir" --solc-binary "./solc"

	# Merge all the generated .json files to produce the target artifact.
	jq --slurp . "$(basename $@)/"*.json --indent 4 > "$@"

output/optimization.json: $(all_sequence_contract_json)
	jq --null-input 'reduce inputs as $$s (.; .[input_filename] += $$s)' $^ --indent 4 > "$@"

$(all_sequence_call_json): \
    output/execution/%.json: \
        output/contracts/$$(word 2, $$(subst /, , $$*)).yul \
        input/sequences/$$(word 1, $$(subst /, , $$*)).txt \
        input/calls/$$(word 2, $$(subst /, , $$*))/$$(word 3, $$(subst /, , $$*)).txt \
        output/optimization/$$(word 1, $$(subst /, , $$*))/$$(word 2, $$(subst /, , $$*)).json \
        execute-all-steps.py

	sequence_name="$(word 1, $(subst /, , $*))"
	contract_name="$(word 2, $(subst /, , $*))"
	call_name="$(word 3, $(subst /, , $*))"
	execution_subdir="$${sequence_name}/$${contract_name}/$${call_name}"
	mkdir -p "output/execution/$${execution_subdir}/"

	output_dir="output/execution/$${sequence_name}/$${contract_name}/$${call_name}/"
	rm -rf "./$${output_dir}/"
	./execute-all-steps.py \
		"output/optimization/$${sequence_name}/$${contract_name}/" \
		"input/calls/$${contract_name}/$${call_name}.txt" \
		--output-dir "$$output_dir" \
		--private-key 0x60b139825a56a987d58b20f0145e05dc45bed12df72cb92812b5ea988383c987

	# Merge all the generated .json files to produce the target artifact.
	jq --slurp . "$(basename $@)/"*.json --indent 4 > "$@"

output/execution.json: $(all_sequence_call_json)
	jq --null-input 'reduce inputs as $$s (.; .[input_filename] += $$s)' $^ --indent 4 > "$@"

$(all_sequence_call_reports_json): \
    output/analysis/%/report.json: \
        output/execution/%.json \
        output/optimization/$$(word 1, $$(subst /, , $$*))/$$(word 2, $$(subst /, , $$*)).json \
        output/optimization/$$(word 1, $$(subst /, , $$*))/$$(word 2, $$(subst /, , $$*))-sequence-info.json \
        analyze-output.py
	sequence_name="$(word 1, $(subst /, , $*))"
	contract_name="$(word 2, $(subst /, , $*))"
	call_name="$(word 3, $(subst /, , $*))"
	./analyze-output.py \
		"output/optimization/$${sequence_name}/$${contract_name}.json" \
		"$<" \
		"output/optimization/$${sequence_name}/$${contract_name}-sequence-info.json" \
		--output-dir "$(dir $@)"

$(all_sequence_call_reports_json:%/report.json=%/table.md): %/table.md: %/report.json visualize-output.py
	./visualize-output.py \
		"$<" \
		--output-dir "$(dir $@)" \
		--document-title "$*"

$(all_sequence_targets): sequence-%: $$(foreach call, $$(calls), output/analysis/$$*/$$(call)/table.md)
$(all_contract_targets): contract-%: $$(foreach sequence, $$(sequences), sequence-$$(sequence)/contract-$$*)

$(all_sequence_contract_targets): \
    %: \
        $$(foreach sequence, $$(sequences), \
            $$(foreach call, $$(filter $$(patsubst contract-$$(percent),$$(percent), $$(word 2, $$(subst /, , $$*)))/$$(percent), $$(calls)), \
                output/analysis/$$(patsubst sequence-$$(percent),$$(percent), $$(word 1, $$(subst /, , $$*)))/$$(call)/table.md \
            ) \
        )

clean-output:
	rm -rf output/
	rm -f sequence-info.json

clean-build:
	rm -rf solidity/

clean: clean-output clean-build

distclean: clean
	rm solc
	rm -rf input/sources/
