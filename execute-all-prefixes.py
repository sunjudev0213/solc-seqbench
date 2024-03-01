#!/usr/bin/env python3

import json
from pathlib import Path
import subprocess
import sys

import click


def fail(message: str | None = None):
    raise click.ClickException(click.style(message if message is not None else "Validation failed.", fg='red'))


def require(condition: bool, message: str | None = None):
    if not condition:
        fail(message)


def deploy_contract(bytecode: str, private_key: str) -> dict:
    return json.loads(subprocess.check_output([
        'cast', 'send',
        '--json',
        '--private-key', private_key,
        '--create', bytecode,
    ]).decode('utf-8'))


def call_contract(address: str, call_signature_and_arguments: list[str], private_key: str) -> dict | str:
    command = [
        'cast', 'send',
        '--json',
        '--private-key', private_key,
        address,
    ] + call_signature_and_arguments

    try:
        output = subprocess.check_output(command, stderr=subprocess.PIPE)
    except subprocess.CalledProcessError as exception:
        if '(code: 3, message: execution reverted, data: Some(String("0x")))' in exception.stderr.decode('utf-8').strip():
            return 'execution-reverted'
        elif '(code: -32603, message: EVM error InvalidFEOpcode, data: None)' in exception.stderr.decode('utf-8').strip():
            return 'invalid-fe-opcode'
        else:
            print(exception.stderr.decode('utf-8'), file=sys.stderr)
        raise

    return json.loads(output.decode('utf-8'))


def load_calls(call_definition_file: Path) -> list[list[str]]:
    calls = []
    for line in call_definition_file.read_text().split('\n'):
        # Remove comments
        clean_line = line.split('#', 1)[0]
        if clean_line == '':
            continue

        calls.append([])
        for argument in clean_line.split(' '):
            if argument == '':
                continue

            clean_argument = argument.strip()
            require(
                # Don't allow arguments that could be interpreted as cast options other than --value.
                not clean_argument.startswith('-') or clean_argument == '--value',
                f"Arguments not allowed in the call (found {clean_argument} in {line})."
            )
            calls[-1].append(clean_argument)

    return calls


def execute_all_steps(bin_dir: Path, call_definition_file: Path, output_dir: Path, private_key: str):
    calls = load_calls(call_definition_file)

    output_dir.mkdir(parents=True, exist_ok=True)
    for dir_item in sorted(bin_dir.iterdir()):
        if not dir_item.is_dir() and dir_item.suffix == '.bin':
            output_file = (output_dir / (dir_item.stem + '.json'))
            print(f"Writing {output_file}")

            # TODO: Deploying once per contract and executing all its sigs in one cycle would be more efficient
            bytecode = dir_item.read_text().strip()
            require(len(bytecode) % 2 == 0, "Invalid bytecode: odd number of hexadecimal digits.")
            require(not bytecode.startswith('0x'), "Expected hex-encoded bytecode, without 0x prefix.")
            creation_info = deploy_contract(bytecode, private_key)

            runtime_gas = 0
            execution_status = 'success'
            for call in calls:
                print(f"Executing call: {' '.join(call)}")
                runtime_info = call_contract(creation_info['contractAddress'], call, private_key)
                if isinstance(runtime_info, str):
                    runtime_gas = None
                    execution_status = runtime_info
                    break
                else:
                    runtime_gas += int(runtime_info['cumulativeGasUsed'], base=16)
                    execution_status = 'success'

            output = json.dumps({
                'file': dir_item.name,
                'bytecode_size': len(bytecode) // 2,
                'creation_gas': int(creation_info['cumulativeGasUsed'], base=16),
                'runtime_gas': runtime_gas,
                'execution_status': execution_status,
            }, indent=4)
            print(output)
            output_file.write_text(output)


@click.command()
@click.argument('bin_dir', nargs=1)
@click.argument('call_definition_file', nargs=1)
@click.option('--output-dir', default='.')
@click.option('--private-key', required=True)
def main(bin_dir: str, call_definition_file: str, output_dir: str, private_key: str):
    execute_all_steps(Path(bin_dir), Path(call_definition_file), Path(output_dir), private_key)


if __name__ == '__main__':
    main()
