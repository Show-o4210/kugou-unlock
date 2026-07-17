"""MMKV 查询结果的文本 / JSON / CSV 输出。"""
from __future__ import annotations

import csv
import io
import json
import sys

def print_table(headers: list[str], rows: list[list[str]], file=sys.stdout) -> None:
    widths = [len(h) for h in headers]
    for row in rows:
        for i, val in enumerate(row):
            widths[i] = max(widths[i], len(str(val)))
            
    border = "+" + "+".join("-" * (w + 2) for w in widths) + "+"
    print(border, file=file)
    print("| " + " | ".join(f"{h:<{widths[i]}}" for i, h in enumerate(headers)) + " |", file=file)
    print(border, file=file)
    for row in rows:
        print("| " + " | ".join(f"{str(val):<{widths[i]}}" for i, val in enumerate(row)) + " |", file=file)
    print(border, file=file)


def format_csv_tsv(mapping: dict[str, any], separator: str, show_types: bool, is_dir_scan: bool) -> str:
    output = io.StringIO()
    writer = csv.writer(output, delimiter=separator, lineterminator="\n")
    
    headers = []
    if is_dir_scan:
        headers.append("File")
    headers.append("Key")
    if show_types:
        headers.append("Type")
    headers.append("Value")
    writer.writerow(headers)
    
    if is_dir_scan:
        for file_path, file_map in sorted(mapping.items()):
            for k, (v_type, v_val) in sorted(file_map.items()):
                row = [file_path, k]
                if show_types:
                    row.append(v_type)
                row.append(str(v_val))
                writer.writerow(row)
    else:
        for k, (v_type, v_val) in sorted(mapping.items()):
            row = [k]
            if show_types:
                row.append(v_type)
            row.append(str(v_val))
            writer.writerow(row)
            
    return output.getvalue()


def format_json(mapping: dict[str, any], show_types: bool, is_dir_scan: bool) -> str:
    if is_dir_scan:
        json_data = {}
        for file_path, file_map in sorted(mapping.items()):
            file_data = {}
            for k, (v_type, v_val) in sorted(file_map.items()):
                if show_types:
                    file_data[k] = {"type": v_type, "value": v_val}
                else:
                    file_data[k] = v_val
            json_data[file_path] = file_data
    else:
        json_data = {}
        for k, (v_type, v_val) in sorted(mapping.items()):
            if show_types:
                json_data[k] = {"type": v_type, "value": v_val}
            else:
                json_data[k] = v_val
                
    return json.dumps(json_data, indent=2, ensure_ascii=False)


def print_text_format(mapping: dict[str, any], show_types: bool, is_dir_scan: bool, no_truncate: bool, file=sys.stdout) -> None:
    if is_dir_scan:
        for file_path, file_map in sorted(mapping.items()):
            print(f"\nFile: {file_path}", file=file)
            print("=" * (len(file_path) + 6), file=file)
            if not file_map:
                print("  (empty)", file=file)
                continue
            headers = ["Key"]
            if show_types:
                headers.append("Type")
            headers.append("Value")
            
            rows = []
            for k, (v_type, v_val) in sorted(file_map.items()):
                val_str = str(v_val)
                if not no_truncate and len(val_str) > 60:
                    val_str = val_str[:57] + "..."
                row = [k]
                if show_types:
                    row.append(v_type)
                row.append(val_str)
                rows.append(row)
            print_table(headers, rows, file=file)
    else:
        if not mapping:
            print("(empty)", file=file)
            return
        headers = ["Key"]
        if show_types:
            headers.append("Type")
        headers.append("Value")
        
        rows = []
        for k, (v_type, v_val) in sorted(mapping.items()):
            val_str = str(v_val)
            if not no_truncate and len(val_str) > 60:
                val_str = val_str[:57] + "..."
            row = [k]
            if show_types:
                row.append(v_type)
            row.append(val_str)
            rows.append(row)
        print_table(headers, rows, file=file)


