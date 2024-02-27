# solc seqbench

## Prerequisites
- make
- wget
- jq
- solc
- Foundry
- Python 3
- click (Python)
- pandas (Python)
- matplotlib (Python)
- cmake
- gcc

## How to run
```bash
./download-sources.sh
```
```bash
make solc
```
```bash
./start-anvil.sh
```
```bash
make
```

### Convenience targets
Build for a single sequence and all contracts:
```bash
make sequence-<sequence name>
```

Build for all sequences and a single contract:
```bash
make contract-<contract name>
```

Build for a single sequence and a single contract:
```bash
make sequence-<sequence name>/contract-<contract name>
```

### Matplotlib visualization
`visualize-output.py` has extra arguments that make it stop and display the output in matplotlib's viewer.
The nice thing about this viewer is that the font size scales down with the zoom level.
This makes it possible to zoom in and see individual steps when they're clustered very close to each other.

To have the build stop after each report and show the plots, you can use the `EXTRA_VISUALIZE_ARGS`
variable to pass in the arguments:
```bash
make sequence-<sequence name>/contract-<contract name> EXTRA_VISUALIZE_ARGS="--show-plot --show-table"
```

Note that this will show plots for a report only when that report is being built.
To see specific plots you need to be specific about the target and also remove the report if it already exists.
