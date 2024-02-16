#!/usr/bin/env python3

import json
from pathlib import Path
from resource import getrusage, RUSAGE_CHILDREN
import subprocess

import click


def fail(message: str | None = None):
    raise click.ClickException(click.style(message if message is not None else "Validation failed.", fg='red'))


def require(condition: bool, message: str | None = None):
    if not condition:
        fail(message)


def extract_artifacts(json_output: str) -> (str, str, dict):
    output = json.loads(json_output)

    if 'errors' in output:
        if (
            len(output['errors']) == 1 and
            output['errors'][0]['type'] == 'InternalCompilerError' and
            'StackTooDeepError' in output['errors'][0]['message']
        ):
            # StackTooDeep may happen with an incomplete sequence. Just continue.
            return (None, None, {'status': 'stack-too-deep'})

        actual_errors = [error['formattedMessage'] for error in output['errors'] if error['type'] not in {"Warning", "Info"}]
        if len(actual_errors) > 0:
            fail("\n    ".join(["Compilation failed."] + actual_errors))

    source_names = list(output['contracts'].keys())
    contract_names = list(output['contracts'][source_names[0]].keys())
    require(len(source_names) == 1 and len(contract_names) == 1, "More than one file or contract found in Standard JSON output.")

    bytecode         = output['contracts'][source_names[0]][contract_names[0]]['evm']['bytecode']['object']
    ir_optimized     = output['contracts'][source_names[0]][contract_names[0]]['irOptimized']
    compilation_info = {'status': 'success'}

    return (bytecode, ir_optimized, compilation_info)


def execute_command_timed(command, standard_input) -> (str, int):
    usage_before = getrusage(RUSAGE_CHILDREN)
    output = subprocess.check_output(
        ['solc', '--standard-json', '-', '--pretty-json', '--json-indent=4'],
        input=standard_input,
    )
    usage_after = getrusage(RUSAGE_CHILDREN)

    # NOTE: ru_time is a floating-point value
    user_mode_cpu_time_in_seconds = usage_after.ru_utime - usage_before.ru_utime
    return (output.decode('utf-8'), user_mode_cpu_time_in_seconds)


def assemble(yul_file: Path, optimizer_steps: str) -> (str, str, dict):
    json_input: dict = {
        'language': 'Yul',
        'sources': {
            str(yul_file): {'urls': [str(yul_file)]}
        },
        'settings': {
            'optimizer': {
                'enabled': True,
                'details': {'yulDetails': {'optimizerSteps': optimizer_steps}},
            },
            'outputSelection': {'*': {'*': ['evm.bytecode.object', 'irOptimized']}},
        }
    }

    (output, cpu_time) = execute_command_timed(
        ['solc', '--standard-json', '-', '--pretty-json', '--json-indent=4'],
        json.dumps(json_input).encode('utf-8'),
    )
    (bytecode, ir_optimized, compilation_info) = extract_artifacts(output)
    return (bytecode, ir_optimized, compilation_info | {'compilation_time': cpu_time})


def validate_sequence(optimizer_steps: str):
    depth = 0
    for i, step in enumerate(optimizer_steps):
        if step == '[':
            depth += 1
        elif step == ']':
            depth -= 1

        require(depth >= 0, f"Found unmatched ']' at position {i}.")

    require(
        ':' not in optimizer_steps or ('[' not in optimizer_steps and ']' not in optimizer_steps),
        f"Cleanup sequence is supported only without nesting."
    )

    require(depth == 0, f"Found unmatched ']' in the sequence")


def iterative_assembler(yul_file: Path, optimizer_steps: str):
    MAX_ITERATIONS = 12
    position = 0
    prefix = ''
    stack = []

    (bytecode, ir, compilation_info) = assemble(yul_file, prefix + ':')
    require(compilation_info['status'] == 'success', "Unoptimized compilation failed.")
    yield (prefix, bytecode, ir, compilation_info)

    while position < len(optimizer_steps):
        step = optimizer_steps[position]
        if str.isspace(step):
            position += 1
        elif step == '[':
            stack.append({'ir': ir, 'iteration': 0, 'start_position': position})
            position += 1
        elif step == ']':
            assert len(stack) > 0

            if stack[-1]['iteration'] >= MAX_ITERATIONS:
                stack.pop()
            elif stack[-1]['ir'] == ir:
                if stack[-1]['ir'] is None or ir is None:
                    fail("Compilation failed at the end of a repeated sequence")
                stack.pop()
            else:
                stack[-1]['iteration'] += 1
                stack[-1]['ir'] = ir
                position = stack[-1]['start_position']
            position += 1
        elif step == ':':
            position += 1
        else:
            # Assume anything else is a step and just let the compiler fail if it's not.
            assert step != ':'

            prefix += step
            position += 1

            (bytecode, ir, compilation_info) = assemble(yul_file, prefix + ':' if ':' not in prefix else prefix)
            yield (prefix, bytecode, ir, compilation_info)

    assert len(stack) == 0


def assemble_with_intermediate_snapshots(yul_file: Path, optimizer_steps: str, output_dir: Path):
    output_dir.mkdir(parents=True, exist_ok=True)
    for i, (prefix, bytecode, ir_optimized, compilation_info) in enumerate(iterative_assembler(Path(yul_file), optimizer_steps)):
        file_basename = f'{yul_file.stem}-step-{i:05d}'
        if len(prefix) > 0:
            file_basename += f'-{prefix[-1]}'
        print(prefix, end='')

        if bytecode is not None:
            (output_dir / f'{file_basename}.yul').write_text(ir_optimized)
        if ir_optimized is not None:
            (output_dir / f'{file_basename}.bin').write_text(bytecode)

        assert compilation_info is not None
        extra_info = {
            'prefix': prefix,
            'step': prefix[-1] if len(prefix) > 0 else None,
            'index': i,
        }
        (output_dir / f'{file_basename}.json').write_text(json.dumps(compilation_info | extra_info, indent=4))
        print(f" | {compilation_info['status']}")


@click.command()
@click.argument('yul_file', nargs=1)
@click.argument('optimizer_steps', nargs=1)
@click.option('--output-dir', default='.')
def main(yul_file: str, optimizer_steps: str, output_dir: str):
    require(Path(yul_file).suffix == '.yul', "Input file must have the .yul extension.")
    validate_sequence(optimizer_steps)
    assemble_with_intermediate_snapshots(Path(yul_file), optimizer_steps, Path(output_dir))


if __name__ == '__main__':
    main()
