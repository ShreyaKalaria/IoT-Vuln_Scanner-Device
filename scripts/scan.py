#!/usr/bin/env python3
"""Automation script for Greenbone scanner 20.08."""

import subprocess
import argparse
import base64
import time
import os
from lxml import etree
from typing import Optional
from typing import Union
from typing import Dict
from typing import List
from typing import Set
from typing import IO

DEBUG: bool = False

scan_profiles: Dict[str, str] = {
    "Discovery": "8715c877-47a0-438d-98a3-27c7a6ab2196",
    "Empty": "085569ce-73ed-11df-83c3-002264764cea",
    "Full and fast": "daba56c8-73ec-11df-a475-002264764cea",
    "Full and fast ultimate": "698f691e-7489-11df-9d8c-002264764cea",
    "Full and very deep": "708f25c4-7489-11df-8094-002264764cea",
    "Full and very deep ultimate": "74db13d6-7489-11df-91b9-002264764cea",
    "Host Discovery": "2d3f051c-55ba-11e3-bf43-406186ea4fc5",
    "System Discovery": "bbca7412-a950-11e3-9109-406186ea4fc5"
}

report_formats: Dict[str, str] = {
    "Anonymous XML": "5057e5cc-b825-11e4-9d0e-28d24461215b",
    "CSV Results": "c1645568-627a-11e3-a660-406186ea4fc5",
    "ITG": "77bd6c4a-1f62-11e1-abf0-406186ea4fc5",
    "PDF": "c402cc3e-b531-11e1-9163-406186ea4fc5",
    "TXT": "a3810a62-1f62-11e1-9219-406186ea4fc5",
    "XML": "a994b278-1f62-11e1-96ac-406186ea4fc5"
}

scan_ports: Dict[str, str] = {
    "All IANA Assigned TCP": "33d0cd82-57c6-11e1-8ed1-406186ea4fc5",
    "All IANA Assigned TCP and UDP": "4a4717fe-57d2-11e1-9a26-406186ea4fc5",
    "All TCP and Nmap top 100 UDP": "730ef368-57e2-11e1-a90f-406186ea4fc5",
}

alive_tests: Set[str] = {
    "Scan Config Default",
    "ICMP, TCP-ACK Service & ARP Ping",
    "TCP-ACK Service & ARP Ping",
    "ICMP & ARP Ping",
    "ICMP & TCP-ACK Service Ping",
    "ARP Ping",
    "TCP-ACK Service Ping",
    "TCP-SYN Service Ping",
    "ICMP Ping",
    "Consider Alive",
}


def check_error(error: str):
    """Print exception error and exit. Ignore OpenVAS temporary authentication error."""
    if 'Failed to authenticate.' not in error:
        print("[ERROR] Response: {}".format(error))
        exit(1)


def execute_command(command: str, xpath: Optional[str] = None) -> Union[str, float, bool, List]:
    """Execute GVMD command and return its output (optionally xpath can be used to get nested XML element)."""
    global DEBUG

    command: str = "su - service -c \"gvm-cli --gmp-username admin --gmp-password admin " \
                   "socket --socketpath /usr/local/var/run/gvmd.sock --xml \'{}\'\"".format(command)

    if DEBUG:
        print("[DEBUG] Command: {}".format(command))

    response: str = ''

    try:
        response = subprocess.check_output(command, stderr=subprocess.STDOUT, shell=True).decode().strip()
    except subprocess.CalledProcessError as e:
        check_error(e.output.decode('utf-8'))

    if DEBUG:
        print("[DEBUG] Response: {}".format(response))

    return etree.XML(response).xpath(xpath) if xpath else response


def perform_cleanup() -> None:
    """Remove all existing tasks and targets."""
    existing_tasks: List = execute_command(r"<get_tasks/>", "//get_tasks_response/task")

    for task in existing_tasks:
        execute_command(r"<delete_task task_id=\"{}\" ultimate=\"true\"/>".format(task.get("id")))

    existing_targets: List = execute_command(r"<get_targets/>", "//get_targets_response/target")

    for target in existing_targets:
       execute_command(r"<delete_target target_id=\"{}\" ultimate=\"true\"/>".format(target.get("id")))


def print_logs() -> None:
    """Show logs from OpenVAS and GVMD."""
    if DEBUG:
        logs: str = open("/usr/local/var/log/gvm/openvas.log", "r").read()

        print("[DEBUG] OpenVAS Logs: {}".format(logs))

        logs: str = open("/usr/local/var/log/gvm/gvmd.log", "r").read()

        print("[DEBUG] GVMD Logs: {}".format(logs))


def save_report(path: str, report: str) -> None:
    """Save report to specified file."""
    file: IO[str] = open(path, 'wb')
    file.write(report)
    file.close()


def get_report(report_id: str, output_format: str) -> Optional[str]:
    """Get generated report. Decode from Base64 if not XML."""
    command: str = r"<get_reports report_id=\"{}\" format_id=\"{}\" ".format(report_id, output_format) + \
                   r"filter=\"apply_overrides=1 overrides=1 notes=1 levels=hmlg\" " + \
                   r"details=\"1\" notes_details=\"1\" result_tags=\"1\" ignore_pagination=\"1\"/>"

    try:
        if output_format == 'a994b278-1f62-11e1-96ac-406186ea4fc5':
            report: etree.Element = execute_command(command, '//get_reports_response/report')[0]
        else:
            report: str = execute_command(command, 'string(//get_reports_response/report/text())')
    except etree.XMLSyntaxError:
        print("Generated report is empty!")

        return None

    return base64.b64decode(report) if isinstance(report, str) else etree.tostring(report).strip()


def process_task(task_id: str) -> str:
    """Wait for task to finish and return report id."""
    status: Optional[str] = None
    task: Optional[str] = None

    while status != "Done":
        try:
            time.sleep(10)

            task = execute_command(r"<get_tasks task_id=\"{}\"/>".format(task_id))
            status = etree.XML(task).xpath("string(//status/text())")
            progress: int = int(etree.XML(task).xpath("string(//progress/text())"))

            os.system("clear")

            if progress > 0:
                print("Task status: {} {}%".format(status, progress))
            else:
                print("Task status: Complete")
        except subprocess.CalledProcessError as exception:
            print("ERROR: ", exception.output)
        except etree.XMLSyntaxError:
            print("ERROR: Cannot get task status")

    return etree.XML(task).xpath("string(//report/@id)")


def start_task(task_id) -> None:
    """Start task with specified id."""
    execute_command(r"<start_task task_id=\"{}\"/>".format(task_id))


def create_task(profile, target_id) -> str:
    """Create new scan task for target."""
    command: str = r"<create_task><name>scan</name>" + \
                   r"<target id=\"{}\"></target>".format(target_id) + \
                   r"<config id=\"{}\"></config></create_task>".format(profile)

    return execute_command(command, "string(//create_task_response/@id)")


def create_target(scan) -> str:
    """Create new target."""
    command: str = r"<create_target><name>scan</name><hosts>{0}</hosts>".format(scan['target']) + \
                   r"<port_list id=\"{}\"></port_list>".format(scan['port_list_id']) + \
                   r"<exclude_hosts>{}</exclude_hosts>".format(scan['exclude']) + \
                   r"<live_tests>{}</live_tests></create_target>".format(scan['tests'])

    return execute_command(command, "string(//create_target_response/@id)")


def make_scan(scan: Dict[str, str]) -> None:
    """Make automated OpenVAS scan and save generated report."""
    perform_cleanup()
    print("Performed initial cleanup.")

    target_id = create_target(scan)
    print("Created target with id: {}.".format(target_id))

    task_id = create_task(scan['profile'], target_id)
    print("Created task with id: {}.".format(task_id))

    start_task(task_id)
    print("Started task.")

    print("Waiting for task to finish...")
    report_id = process_task(task_id)
    print("Finished processing task.")

    report = get_report(report_id, scan['format'])
    print("Generated report.")

    if report:
        save_report(scan['output'], report)
        print("Saved report to {}.".format(scan['output']))

    print_logs()
    perform_cleanup()
    print("Done!")


def start_scan(args: argparse.Namespace) -> None:
    """Override default settings and start scan."""
    global DEBUG

    if args.debug:
        DEBUG = True

    subprocess.check_call(
        ["sed -i 's/max_hosts.*/max_hosts = " + str(args.hosts) + "/' /usr/local/etc/openvas/openvas.conf"],
        shell=True,
        stdout=subprocess.DEVNULL
    )
    subprocess.check_call(
        ["sed -i 's/max_checks.*/max_checks = " + str(args.checks) + "/' /usr/local/etc/openvas/openvas.conf"],
        shell=True,
        stdout=subprocess.DEVNULL
    )

    if args.update is True:
        print("Starting and updating OpenVAS...")
        subprocess.check_call(["update-scanner"], shell=True, stdout=subprocess.DEVNULL)
    else:
        print("Starting OpenVAS...")
        subprocess.check_call(["start-scanner"], shell=True, stdout=subprocess.DEVNULL)

    print("Starting scan with settings:")
    print("* Target: {}".format(args.target))
    print("* Excluded hosts: {}".format(args.exclude))
    print("* Scan profile: {}".format(args.profile))
    print("* Scan ports: {}".format(args.ports))
    print("* Alive tests: {}".format(args.tests))
    print("* Max hosts: {}".format(args.hosts))
    print("* Max checks: {}".format(args.checks))
    print("* Report format: {}".format(args.format))
    print("* Output file: {}\n".format(args.output))

    make_scan({'target': args.target, 'exclude': args.exclude, 'tests': args.tests.replace("&", "&amp;"),
               'profile': scan_profiles[args.profile], 'port_list_id': scan_ports[args.ports],
               'format': report_formats[args.format], 'output': "/reports/" + args.output})


def report_format(arg: Optional[str]) -> str:
    """Check if report format value is valid."""
    if arg not in report_formats:
        raise argparse.ArgumentTypeError("Specified report format is invalid!")

    return arg


def scan_profile(arg: Optional[str]) -> str:
    """Check if scan profile value is valid."""
    if arg not in scan_profiles:
        raise argparse.ArgumentTypeError("Specified scan profile is invalid!")

    return arg

def scan_ports_option(arg: Optional[str]) -> str:
    """Check if scan ports value is valid."""
    if arg not in scan_ports:
        raise argparse.ArgumentTypeError("Specified scan ports option is invalid!")

    return arg


def alive_test(arg: Optional[str]) -> str:
    """Check if alive test value is valid."""
    if arg not in alive_tests:
        raise argparse.ArgumentTypeError("Specified alive tests are invalid!")

    return arg


def max_hosts(arg: Optional[str]) -> int:
    """Check if max hosts value is valid."""
    try:
        value = int(arg)

        if value <= 0:
            raise ValueError
    except ValueError:
        raise argparse.ArgumentTypeError("Specified maximum number of simultaneous tested hosts is invalid!")

    return value


def max_checks(arg: Optional[str]) -> int:
    """Check if max checks value is valid."""
    try:
        value = int(arg)

        if value <= 0:
            raise ValueError
    except ValueError:
        raise argparse.ArgumentTypeError("Specified maximum number of simultaneous checks against hosts is invalid!")

    return value


def parse_arguments():
    """Add and parse script arguments."""
    parser: argparse.ArgumentParser = argparse.ArgumentParser(
        description='Run OpenVAS scan with specified target and save report.')
    parser.add_argument('target', help='scan target')
    parser.add_argument('-o', '--output', help='output file (default: openvas.report)',
                        default="openvas.report", required=False)
    parser.add_argument('-f', '--format', help='format for report (default: XML)',
                        default="XML", type=report_format, required=False)
    parser.add_argument('-p', '--profile', help='scan profile (default: )',
                        default="Full and fast", type=scan_profile, required=False)
    parser.add_argument('-P', '--ports', help='scan ports (default: All TCP and Nmap top 100 UDP)',
                        default="All TCP and Nmap top 100 UDP", type=scan_ports_option, required=False)
    parser.add_argument('-t', '--tests', help='alive tests (default: ICMP, TCP-ACK Service & ARP Ping)',
                        default="ICMP, TCP-ACK Service & ARP Ping", type=alive_test, required=False)
    parser.add_argument('-e', '--exclude', help='hosts excluded from scan target (Default: "")',
                        default="", required=False)
    parser.add_argument('-m', '--hosts', help='maximum number of simultaneous tested hosts (Default: 15)',
                        type=max_hosts, default=10, required=False)
    parser.add_argument('-c', '--checks', help='maximum number of simultaneous checks against each host (Default: 5)',
                        type=max_checks, default=3, required=False)
    parser.add_argument('--update', help='synchronize feeds before scanning',
                        nargs='?', const=True, default=False, required=False)
    parser.add_argument('--debug', help='enable command responses printing',
                        nargs='?', const=True, default=False, required=False)

    return parser.parse_args()


if __name__ == '__main__':
    arguments: argparse.Namespace = parse_arguments()

    start_scan(arguments)
