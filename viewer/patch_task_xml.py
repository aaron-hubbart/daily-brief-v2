#!/usr/bin/env python3
"""Patch a Scheduled Task XML export to allow running on battery power.

Windows' schtasks XML export defaults to DisallowStartIfOnBatteries=true and
StopIfGoingOnBatteries=true, which would pause the Daily Brief Viewer whenever
a laptop is unplugged. This flips both to false in a copy of the XML so the
task can be re-imported with schtasks /create ... /xml.

Usage: patch_task_xml.py <input_xml_path> <output_xml_path>
"""
import sys


def main():
    if len(sys.argv) != 3:
        print("Usage: patch_task_xml.py <input_xml_path> <output_xml_path>")
        sys.exit(1)

    input_path, output_path = sys.argv[1], sys.argv[2]

    try:
        with open(input_path, "r", encoding="utf-16") as f:
            xml = f.read()

        xml = xml.replace(
            "<DisallowStartIfOnBatteries>true</DisallowStartIfOnBatteries>",
            "<DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>",
        )
        xml = xml.replace(
            "<StopIfGoingOnBatteries>true</StopIfGoingOnBatteries>",
            "<StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>",
        )

        with open(output_path, "w", encoding="utf-16") as f:
            f.write(xml)

        print("Power settings patched.")
    except Exception as e:
        print("Could not patch power settings:", e)
        sys.exit(1)


if __name__ == "__main__":
    main()
