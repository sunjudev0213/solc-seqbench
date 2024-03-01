# Execute whole rules in one shell invocation (instead a separete shell for every line) and fail on first error
.ONESHELL:
.SHELLFLAGS += -euo pipefail

.SECONDEXPANSION:

sequence_names := $(basename $(notdir $(wildcard input/sequences/*.txt)))
contract_names := $(basename $(notdir $(wildcard input/contracts/*.json)))
call_names     := \
    $(foreach contract, $(contract_names), \
        $(addprefix $(contract)/, \
            $(basename $(notdir $(wildcard input/calls/$(contract)/*.txt))) \
        ) \
    )

all_sequence_info_jsons := \
    $(foreach sequence, $(sequence_names), \
        $(foreach contract, $(contract_names), \
            output/optimization/$(sequence)/$(contract)-sequence-info.json \
        ) \
    )

all_optimization_info_jsons := \
    $(foreach sequence, $(sequence_names), \
        $(foreach contract, $(contract_names), \
            output/optimization/$(sequence)/$(contract)-optimization-info.json \
        ) \
    )

all_execution_info_jsons := \
    $(foreach sequence, $(sequence_names), \
        $(foreach call, $(call_names), \
            output/execution/$(sequence)/$(call)-execution-info.json \
        ) \
    )

all_analysis_jsons := \
    $(foreach sequence, $(sequence_names), \
        $(foreach call, $(call_names), \
            output/analysis/$(sequence)/$(call)/report.json \
        ) \
    )

all_per_sequence_reports := $(foreach sequence, $(sequence_names), output/analysis-per-sequence/$(sequence)/report.md)
all_per_contract_reports := $(foreach contract, $(contract_names), output/analysis-per-contract/$(contract)/report.md)

# Convenience targets for selecting specific contracts/sequences
all_sequence_targets := $(foreach sequence, $(sequence_names), sequence-$(sequence))
all_contract_targets := $(foreach contract, $(contract_names), contract-$(contract))
all_sequence_contract_targets := \
    $(foreach sequence, $(sequence_names), \
        $(foreach contract, $(contract_names), \
            sequence-$(sequence)/contract-$(contract) \
        ) \
    )

define sequence-segment
$(word 1, $(subst /, , $(1)))
endef

define contract-segment
$(word 2, $(subst /, , $(1)))
endef

define call-segment
$(word 3, $(subst /, , $(1)))
endef

define contract-from-contract-sequence-target
$(patsubst contract-%,%, $(call contract-segment, $(1)))
endef

define sequence-from-contract-sequence-target
$(patsubst sequence-%,%, $(call sequence-segment, $(1)))
endef

define analysis-jsons-matching-contract-name
$(foreach call, $(filter $(1)/%, $(call_names)), \
    $(foreach sequence, $(sequence_names), \
        output/analysis/$(sequence)/$(call)/report.json \
    ) \
)
endef

define call-names-matching-contract
$(filter $(call contract-from-contract-sequence-target, $(1))/%, $(call_names))
endef

define reports-matching-sequence-contract-target
$(foreach sequence, $(sequence_names), \
    $(foreach call, $(call call-names-matching-contract, $(1)), \
        output/analysis/$(call sequence-from-contract-sequence-target, $(1))/$(call)/report.md \
    ) \
)
endef

.PHONY: \
    all \
    clean \
    assembly \
    optimization \
    execution \
    analysis \
    $(all_sequence_targets) \
    $(all_contract_targets) \
    $(all_sequence_contract_targets)

all: analysis

assembly: $(foreach c, $(contract_names), output/assembly/$(c).yul)
optimization: output/optimization-info.json
execution: output/execution-info.json
analysis: $(all_sequence_targets) $(all_contract_targets) $(all_sequence_contract_targets)

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

output/assembly/:
	mkdir -p "$(dir $@)"

output/assembly/%.json: input/contracts/%.json | output/assembly/
	cd input/contracts/
	solc --standard-json "$(notdir $<)" --allow-paths ../sources/ --pretty-json --json-indent 4 > "../../$@"

	errors=$$(jq '.errors[] | select(.type == "Error")' --indent 4 "../../$@")
	[[ $$errors == "" ]] || { >&2 echo "$$errors"; false; }

output/assembly/%.yul: output/assembly/%.json
	jq --raw-output '.contracts | to_entries[0].value | to_entries[0].value.ir' --indent 4 "$<" > "$@" || { >&2 cat "$<"; false; }

$(all_sequence_info_jsons): \
    output/optimization/%-sequence-info.json: \
    output/assembly/$$(call contract-segment, $$*).yul \
    input/sequences/$$(call sequence-segment, $$*).txt

	sequence_name="$(call sequence-segment, $*)"
	contract_name="$(call contract-segment, $*)"

	# Load sequence but strip comments from line ends and remove empty lines
	sequence=$$(sed -e 's|^\([^#]*\).*$$|\1|g' -e '/^\s*$$/d' "input/sequences/$${sequence_name}.txt")

	# Run patched solc that can dump internal information about the sequence, including which steps
	# actually run and timing info of the optimization alone.
	output_dir="output/optimization/$${sequence_name}/$${contract_name}/"
	export SOLC_DUMP_SEQUENCE_INFO=1
	./solc --strict-assembly "$<" --optimize --yul-optimizations "$$sequence" --ir-optimized > /dev/null
	mkdir -p "$(dir $@)"
	mv sequence-info.json "$@"

$(all_optimization_info_jsons): \
    output/optimization/%-optimization-info.json: \
    output/assembly/$$(call contract-segment, $$*).yul \
    input/sequences/$$(call sequence-segment, $$*).txt \
    output/optimization/$$(call sequence-segment, $$*)/$$(call contract-segment, $$*)-sequence-info.json \
    optimize-all-prefixes.py

	sequence_name="$(call sequence-segment, $*)"
	contract_name="$(call contract-segment, $*)"
	sequence_info_file="output/optimization/$${sequence_name}/$${contract_name}-sequence-info.json"
	flattened_sequence=$$(jq '.[0].flattened_sequence_no_hardcoded' "$$sequence_info_file" --raw-output)

	# Generate a .json file for each step, containing info about compilation.
	# For those steps that did not fail with StackTooDeep error, a .yul file is also generated.
	output_dir="output/optimization/$${sequence_name}/$${contract_name}/"
	rm -rf "./$${output_dir}/"
	./optimize-all-prefixes.py "$<" "$$flattened_sequence" --output-dir "$$output_dir" --solc-binary "./solc"

	# Merge all the generated .json files to produce the target artifact.
	jq --slurp . "$(patsubst %-optimization-info.json,%,$@)/"*.json --indent 4 > "$@"

output/optimization-info.json: $(all_optimization_info_jsons)
	jq --null-input 'reduce inputs as $$s (.; .[input_filename] += $$s)' $^ --indent 4 > "$@"

$(all_execution_info_jsons): \
    output/execution/%-execution-info.json: \
        input/sequences/$$(call sequence-segment, $$*).txt \
        input/calls/$$(call contract-segment, $$*)/$$(call call-segment, $$*).txt \
        output/optimization/$$(call sequence-segment, $$*)/$$(call contract-segment, $$*)-optimization-info.json \
        execute-all-prefixes.py

	sequence_name="$(call sequence-segment, $*)"
	contract_name="$(call contract-segment, $*)"
	call_name="$(call call-segment, $*)"
	execution_subdir="$${sequence_name}/$${contract_name}/$${call_name}"
	mkdir -p "output/execution/$${execution_subdir}/"

	output_dir="output/execution/$${sequence_name}/$${contract_name}/$${call_name}/"
	rm -rf "./$${output_dir}/"
	./execute-all-prefixes.py \
		"output/optimization/$${sequence_name}/$${contract_name}/" \
		"input/calls/$${contract_name}/$${call_name}.txt" \
		--output-dir "$$output_dir" \
		--private-key 0x60b139825a56a987d58b20f0145e05dc45bed12df72cb92812b5ea988383c987

	# Merge all the generated .json files to produce the target artifact.
	jq --slurp . "$(patsubst %-execution-info.json,%,$@)/"*.json --indent 4 > "$@"

output/execution-info.json: $(all_execution_info_jsons)
	jq --null-input 'reduce inputs as $$s (.; .[input_filename] += $$s)' $^ --indent 4 > "$@"

$(all_analysis_jsons): \
    output/analysis/%/report.json: \
        output/execution/%-execution-info.json \
        output/optimization/$$(call sequence-segment, $$*)/$$(call contract-segment, $$*)-optimization-info.json \
        output/optimization/$$(call sequence-segment, $$*)/$$(call contract-segment, $$*)-sequence-info.json \
        analyze-output.py

	sequence_name="$(call sequence-segment, $*)"
	contract_name="$(call contract-segment, $*)"
	call_name="$(call call-segment, $*)"
	./analyze-output.py \
		"output/optimization/$${sequence_name}/$${contract_name}-optimization-info.json" \
		"$<" \
		"output/optimization/$${sequence_name}/$${contract_name}-sequence-info.json" \
		--output-dir "$(dir $@)"

$(all_analysis_jsons:%/report.json=%/report.md): %/report.md: %/report.json visualize-output.py
	./visualize-output.py \
		"$<" \
		--output-dir "$(dir $@)" \
		--document-title "$*" \
		$(EXTRA_VISUALIZE_ARGS)

$(all_per_sequence_reports): \
    output/analysis-per-sequence/%/report.md: \
        $$(foreach call, $$(call_names), output/analysis/$$*/$$(call)/report.json) \
        visualize-output.py

	reports_and_names=($(foreach call, $(call_names), output/analysis/$*/$(call)/report.json --report-name $(call)))

	./visualize-output.py \
		"$${reports_and_names[@]}" \
		--output-dir "$(dir $@)" \
		--document-title "Sequence $*, all contracts and calls" \
		$(EXTRA_VISUALIZE_ARGS)

$(all_per_contract_reports): \
    output/analysis-per-contract/%/report.md: \
        $(call analysis-jsons-matching-contract-name, $*) \
        visualize-output.py

	reports_and_names=(
		$(foreach call, $(filter $*/%, $(call_names)), \
			$(foreach sequence, $(sequence_names), \
				output/analysis/$(sequence)/$(call)/report.json --report-name $(sequence)/$(patsubst $*/%,%, $(call)) \
			) \
		)
	)

	./visualize-output.py \
		"$${reports_and_names[@]}" \
		--output-dir "$(dir $@)" \
		--document-title "Contract $*, all sequences and calls" \
		$(EXTRA_VISUALIZE_ARGS)

$(all_sequence_targets): sequence-%: output/analysis-per-sequence/$$*/report.md
$(all_contract_targets): contract-%: output/analysis-per-contract/$$*/report.md

$(all_sequence_contract_targets): %: $$(call reports-matching-sequence-contract-target, $$*)

clean-output:
	rm -rf output/
	rm -f sequence-info.json

clean-build:
	rm -rf solidity/

clean: clean-output clean-build

distclean: clean
	rm solc
	rm -rf input/sources/
