#! /usr/bin/env python3

from clint.textui import colored, puts
import argparse
import re
import yaml
from pathlib import Path
from textwrap import dedent, TextWrapper

import sys
YARA_VALIDATOR_PATH = Path(__file__).resolve().parent / Path("yara-validator")
if YARA_VALIDATOR_PATH not in sys.path:
    sys.path.append(str(YARA_VALIDATOR_PATH))

import yara_validator

STANDARD_YAML_PATH = Path(__file__).resolve().parent / Path("CCCS_Yara.yml")
YARA_FILENAME_REGEX = "(\.yara|\.yar)$"
YARA_VALID_PREFIX = "valid_"
YARA_VALID_PREFIX_REG = re.compile("^" + YARA_VALID_PREFIX)

# Defining the parser and arguments to parse so it be used both when called by the command line and with the git_ci
# function.
parser = argparse.ArgumentParser(description="CCCS YARA script to run the CCCS YARA validator, "
                                             "if the -i or -c flags are not provided no changes "
                                             "will be made to the files.")
parser.add_argument('paths', nargs='+', type=str, default=[],
                    help="A list of files or folders to be analyzed.")
parser.add_argument('-r', '--recursive', action='store_true', default=False, dest='recursive',
                    help="Recursively search folders provided.")
parser.add_argument('-n', '--no-changes', action='store_true', default=False, dest='nochanges',
                    help="Makes no changes and outputs potential results to the output.")
parser.add_argument('-v', '--verbose', action='store_true', default=False, dest='verbose',
                    help="Verbose mode, will print why a rule was invalid.")
parser.add_argument('-vv', '--very-verbose', action='store_true', default=False, dest='veryverbose',
                    help="Very-verbose mode, will printout what rule is about to be processed, "
                         "the invalid rules, the reasons they are invalid and all contents of the rule.")
parser.add_argument('-f', '--fail', action='store_true', default=False, dest='fail',
                    help="Fail mode, only prints messages about invalid rules.")
parser.add_argument('-w', '--warnings', action='store_true', default=False, dest='warnings',
                    help="This mode will ignore warnings and proceed with other behaviors if the rule is valid.")
parser.add_argument('-s', '--standard', action='store_true', default=False, dest='standard',
                    help="This prints the yara standard to the screen.")

parser_group = parser.add_mutually_exclusive_group()
parser_group.add_argument('-i', '--in-place', action='store_true', default=False, dest='inplace',
                          help="Modifies valid files in place, mutually exclusive with -c.")
parser_group.add_argument('-c', '--create-files', action='store_true', default=False, dest='createfile',
                          help="Writes a new file for each valid file, mutually exclusive with -i.")

def parse_args():
    options = parser.parse_args()

    return options

def get_yara_paths_from_dir(directory, recursive):
    """ Recursively get yara rules from a directory """

    if directory.is_file() and re.fullmatch(YARA_FILENAME_REGEX, directory.suffix):
        yield directory
    elif directory.is_dir():
        for path in list(directory.iterdir()):
            if path.is_file() and re.fullmatch(YARA_FILENAME_REGEX, path.suffix):
                yield path
            elif path.is_dir() and recursive:
                for sub_dir_path in get_yara_paths_from_dir(path, recursive):
                    yield sub_dir_path

def get_paths_to_validate(options_paths, recursive):
    """ Returns a set of pathlib.Path objects for all
        yara rules that will be validated """

    paths_to_validate = set()

    for path in [Path(path_name) for path_name in options_paths]:
        if path.exists():
            if path.is_dir():
                paths_to_validate.update(get_yara_paths_from_dir(path, recursive))
            elif re.match(YARA_FILENAME_REGEX, path.suffix):
                paths_to_validate.add(path)
        else:
            print("{message:40}{path}".format(message="Path does not exist:",path=str(path)))

    return sorted(paths_to_validate)


def get_yara_file_new_path(path):
    """ takes a path in argument, and return the same path with the 
        filename prefixed with YARA_VALID_PREFIX.

        if the file already has the prefix, returns the path unchanged.
    """
    if YARA_VALID_PREFIX_REG.match(path.name):
        return path
    else:
        new_name = YARA_VALID_PREFIX + path.name
        return path.parent / new_name

def overwrite_file(path, content):
    with open(path, 'w', encoding='utf-8') as f:
        f.write(content)

def print_errors(rule_return, options):
    if not rule_return.rule_validity:
        print(colored.red("{indent:>7}{message}".format(indent="- ", message="Errors:")))
        print(colored.white(rule_return.return_errors_for_cmlt()))

def print_warnings(rule_return, options):
    if rule_return.rule_warnings and not options.warnings:
        print(colored.yellow("{indent:>7}{message}".format(indent="- ", message="Warnings:")))
        print(colored.white(rule_return.return_warnings_for_cmlt()))

def print_standard():
    print("Printing the CCCS YARA Standard:")
    with open(STANDARD_YAML_PATH, "r") as yaml_file:
        standard = yaml.safe_load(yaml_file)

    for standard_key in standard:
        standard_entry_name = standard_key
        standard_entry_description = standard[standard_key]['description']
        standard_entry_unique = standard[standard_key]['unique']
        standard_entry_optional = standard[standard_key]['optional']
        standard_entry_format = standard[standard_key]['format']
        print("{se_name}{message}".format(message=":",
                                            se_name=standard_entry_name))
        print("{preface:20}{se_text}".format(preface="     - Description:",
                                                se_text=standard_entry_description))
        print("{preface:20}{se_text}".format(preface="     - Format:",
                                             se_text=standard_entry_format))
        print("{preface:20}{se_text}".format(preface="     - Unique:",
                                                se_text=standard_entry_unique))
        print("{preface:20}{se_text}".format(preface="     - Optional:",
                                                se_text=standard_entry_optional))
        if 'validator' in standard[standard_key]:
            standard_entry_validator = standard[standard_key]['validator']
            print("{preface:20}{se_text}".format(preface="     - Validator:",
                                                 se_text=standard_entry_validator))
        if 'argument' in standard[standard_key]:
            standard_entry_argument = standard[standard_key]['argument']
            print("{preface:20}{se_text}".format(preface="     - Argument:",
                                                 se_text=""))
            for param in standard_entry_argument:
                print("{preface:20}{se_text}".format(preface="       - " + param + ": ",
                                                     se_text=standard_entry_argument[param]))
        print()


def __call_validator(options):
    paths_to_validate = get_paths_to_validate(options.paths,
                                              options.recursive)

    all_invalid_rule_returns = []
    all_warning_rule_returns = []

    if options.standard:
        print_standard()

    # main loop : will iterate over every file the program has to validate,
    #             validate them and then print the output
    for yara_rule_path in list(paths_to_validate):
        if options.veryverbose:
            print("{message:40}{y_file}".format(message="Validating Rule file:",
                                                y_file=yara_rule_path))

        rule_return = yara_validator.run_yara_validator(yara_rule_path)
        what_will_be_done = "make no changes"
        yara_file_output = None

        # handle if we want to overwrite or create new files
        if options.createfile:
            yara_file_output = get_yara_file_new_path(yara_rule_path)
            what_will_be_done = "create a new file with the {} preface.".format(YARA_VALID_PREFIX)
        elif options.inplace:
            yara_file_output = yara_rule_path
            what_will_be_done = "modify the file in place."

        # Prints the output of the validator.
        if not rule_return.rule_validity:
            # The rule is invalid

            all_invalid_rule_returns.append((yara_rule_path, rule_return))

            puts(colored.red("{message:39}{y_file}".format(message="🍩 Invalid Rule File:",
                                                           y_file=yara_rule_path)))

            if options.nochanges:
                print("     - Would {message}".format(message=what_will_be_done))

            if options.verbose or options.veryverbose:
                print_errors(rule_return, options)
                print_warnings(rule_return, options)

        elif rule_return.rule_warnings and not options.warnings:
            # The rule is valid, has warnings and warning are turned on

            all_warning_rule_returns.append((yara_rule_path, rule_return))

            puts(colored.yellow("{message:38}{y_file}".format(message="   Warnings in Rule File:",
                                                              y_file=yara_rule_path)))

            if options.verbose or options.veryverbose:
                print_warnings(rule_return, options)

        elif rule_return.rule_validity:
            # The rule is valid with no warnings or has warnings and warnings are turned off

            if not options.fail:
                print("{message:40}{y_file}".format(message="   Valid Rule File:",
                                                    y_file=yara_rule_path))
            if options.nochanges:
                print("     - Would {message}".format(message=what_will_be_done))
            elif options.inplace or options.createfile:
                overwrite_file(yara_file_output, rule_return.return_validated_rule())

        else:
            print("Danger Will Robinson! Danger!"
                  "Seriously though, how on earth did you get here???")

    if options.veryverbose:
        for invalid_rule_path, invalid_rule_return in all_invalid_rule_returns:
            print(dedent("""
            ----------------------------------------------------------------------------
            Invalid rule file:{invalid_rule_path}
            Warnings:
            {rule_warnings}
            Errors:
            {rule_errors}
            {original_rule}
            ----------------------------------------------------------------------------
            """).format(rule_warnings=invalid_rule_return.return_warnings_for_cmlt(),
                        rule_errors=invalid_rule_return.return_errors_for_cmlt(),
                        original_rule=invalid_rule_return.return_original_rule(),
                        invalid_rule_path=invalid_rule_path))

    total_yara_rule_paths = len(paths_to_validate)
    total_invalid_yara_rule_paths = len(all_invalid_rule_returns)
    total_warning_yara_rule_paths = len(all_warning_rule_returns)
    total_valid_yara_rule_paths = (total_yara_rule_paths
                                   - total_invalid_yara_rule_paths
                                   - total_warning_yara_rule_paths)

    print(dedent("""
    ----------------------------------------------------------------------------
    All .yara Rule files found have been passed through the CCCS Yara Validator:
        Total Yara Rule Files to Analyze:     {total_yara_rule_paths}
        Total Valid CCCS Yara Rule Files:     {total_valid_yara_rule_paths} 
        Total Warning CCCS Yara Rule Files:   {total_warning_yara_rule_paths}
        Total Invalid CCCS Yara Rule Files:   {total_invalid_yara_rule_paths} 
    ---------------------------------------------------------------------------
    """).format(total_yara_rule_paths=str(total_yara_rule_paths),
                total_valid_yara_rule_paths=colored.green(str(total_valid_yara_rule_paths)),
                total_warning_yara_rule_paths=colored.yellow(str(total_warning_yara_rule_paths)),
                total_invalid_yara_rule_paths=colored.red(str(total_invalid_yara_rule_paths))))

    if total_invalid_yara_rule_paths >= 1:
        exit(99)

def git_ci(changed_file_paths):
    options = parser.parse_args(changed_file_paths)
    __call_validator(options)

def main():
    print('''\
     ____ ____ ____ ____   __   __ _    ____      _    
    / ___/ ___/ ___/ ___|  \ \ / // \  |  _ \    / \   
   | |  | |  | |   \___ \   \ V // _ \ | |_) |  / _ \  
   | |__| |__| |___ ___) |   | |/ ___ \|  _ <  / ___ \ 
    \____\____\____|____/    |_/_/   \_\_| \_\/_/   \_\ 
    ''')


    options = parse_args()

    __call_validator(options)

if __name__ == "__main__":
    main()
