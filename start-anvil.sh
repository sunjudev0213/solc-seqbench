#!/usr/bin/env bash
set -eou pipefail

export seed="grace crime cat remove spice bean concert lawsuit render horse collect vocal"
export key=0x60b139825a56a987d58b20f0145e05dc45bed12df72cb92812b5ea988383c987

# Give test accounts a high amount of ETH so that they don't easily run out on repeated calls with value.
# All calls are executed from the same account in the same anvil session.
anvil --mnemonic "$seed" --balance 1000000000
