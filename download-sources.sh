#!/usr/bin/env bash
set -eou pipefail

mkdir -p input/sources/
cd input/sources/

rm -rf solidity/
git clone https://github.com/ethereum/solidity/ --branch v0.8.24 --depth 1
find solidity/ -type f,l      -not -path 'solidity/test/libsolidity/semanticTests/externalContracts/*' -delete
find solidity/ -type d -empty -not -path 'solidity/test/libsolidity/semanticTests/externalContracts'   -delete
sed -i -e '/^==== .* ====$/d' solidity/test/libsolidity/semanticTests/externalContracts/strings.sol
sed -i -e '/^==== .* ====$/d' solidity/test/libsolidity/semanticTests/externalContracts/ramanujan_pi.sol
sed -i -e '/^==== .* ====$/d' solidity/test/libsolidity/semanticTests/externalContracts/prbmath_unsigned.sol
