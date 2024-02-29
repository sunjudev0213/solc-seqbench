#!/usr/bin/env bash
set -eou pipefail

mkdir -p input/sources/
cd input/sources/

rm -rf solidity/
git clone https://github.com/ethereum/solidity/ --branch v0.8.24 --depth 1
rm -rf solidity/.git
