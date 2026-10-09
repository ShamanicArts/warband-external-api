#!/usr/bin/env python3
"""
Build Module — generates Warband compiled .txt files for the ExternalAPI module.

This creates a minimal module based on Native with additional simple_triggers
that enable file I/O for external system communication.

Usage:
    python3 build_module.py [--output-dir PATH]
"""

import argparse
import os
import shutil
import sys
from pathlib import Path

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from header_operations import *

# ── Configuration ──────────────────────────────────────────────────

GAME_DIR = Path(
    os.environ.get(
        "WARBAND_DIR",
        "/home/shamanic/.local/share/Steam/steamapps/common/MountBlade Warband"
    )
)

NATIVE_DIR = GAME_DIR / "Modules" / "Native"
DEFAULT_OUTPUT = GAME_DIR / "Modules" / "ExternalAPI"

# ── String Table ───────────────────────────────────────────────────

# These strings will be added to strings.txt
STRINGS = {
    "str_external_api_state_txt": "external_api_state.txt",
    "str_external_api_cmd_txt": "external_api_cmd.txt",
    "str_external_api_state_init": "STATE_INIT",
    "str_state_prefix": "STATE:",
    "str_cmd_prefix": "CMD:",
}

# ── File I/O Operations Builder ───────────────────────────────────

class CompiledBuilder:
    """
    Builds compiled .txt format for Warband module system operations.
    
    Format: <opcode> <num_params> <param1> [param2 ...]
    """
    
    def __init__(self):
        self.ops = []
        self.next_reg = 0
        
    def _reg(self):
        """Get next local register. Registers are from 1224979098644774912 upward."""
        reg = 1224979098644774912 + self.next_reg
        self.next_reg += 1
        return reg
    
    def _str_reg(self, index=0):
        """String register reference. s0 = 0, s1 = 1, etc."""
        return index
    
    def op(self, opcode, *params):
        """Add an operation: opcode followed by param count then params."""
        self.ops.append((opcode, len(params), list(params)))
        return self
    
    def try_begin(self):
        """try_begin block"""
        self.op(try_begin)
        return self
    
    def try_end(self):
        """end try block"""
        self.op(try_end)
        return self
    
    def else_op(self):
        """else block"""
        self.op(else_op)
        return self
    
    def assign(self, dest, value):
        """val_set dest = value"""
        self.op(val_set, dest, value)
        return self
    
    def add(self, var, amount):
        """val_add var += amount"""
        self.op(val_add, var, amount)
        return self
    
    def sub(self, var, amount):
        """val_sub var -= amount"""
        self.op(val_sub, var, amount)
        return self
    
    def ge(self, a, b):
        """condition: a >= b"""
        self.op(ge, a, b)
        return self
    
    def eq(self, a, b):
        """condition: a == b"""
        self.op(eq, a, b)
        return self
    
    def lt(self, a, b):
        """condition: a < b"""
        self.op(lt, a, b)
        return self
    
    def open_write_file(self, file_reg, filename_str_reg):
        """open_write_file file_reg, filename_string"""
        self.op(open_write_file, file_reg, filename_str_reg)
        return self
    
    def open_read_file(self, file_reg, filename_str_reg):
        """open_read_file file_reg, filename_string"""
        self.op(open_read_file, file_reg, filename_str_reg)
        return self
    
    def write_to_file(self, file_reg, content_str_reg):
        """write_to_file file_reg, content_string"""
        self.op(write_to_file, file_reg, content_str_reg)
        return self
    
    def read_from_file(self, result_str_reg, file_reg):
        """read_from_file result_string, file_reg"""
        self.op(read_from_file, result_str_reg, file_reg)
        return self
    
    def close_file(self, file_reg):
        """close_file file_reg"""
        self.op(close_file, file_reg)
        return self
    
    def str_store(self, dest_str_reg, string_id):
        """Store a string table entry into a string register"""
        self.op(str_store_string, dest_str_reg, string_id)
        return self
    
    def display(self, string_id_or_reg):
        """Display a message"""
        self.op(display_message, string_id_or_reg)
        return self
    
    def party_set_slot(self, party_id, slot_no, value):
        self.op(party_set_slot, party_id, slot_no, value)
        return self
    
    def party_get_slot(self, dest, party_id, slot_no):
        self.op(party_get_slot, dest, party_id, slot_no)
        return self
    
    def compile(self):
        """Return the compiled line as a space-separated string."""
        tokens = []
        for (opcode, nparams, params) in self.ops:
            tokens.append(str(opcode))
            tokens.append(str(nparams))
            if nparams > 0:
                for p in params:
                    tokens.append(str(p))
        return " ".join(tokens)
    
    def num_ops(self):
        """Return the total number of operations."""
        return len(self.ops)


def build_simple_triggers():
    """Build simple_triggers.txt with file I/O state dump + command polling."""
    
    # ── Trigger 1: Dump world state every 3 seconds ──
    t1 = CompiledBuilder()
    
    # Registers:
    fh = 1          # file handle register
    s_fname = 10    # string register for state filename
    s_content = 11  # string register for content
    test_val = t1._reg()
    counter = t1._reg()
    
    # Open file for writing
    t1.str_store(s_fname, "str_external_api_state_txt")  # s10 = "external_api_state.txt"
    t1.open_write_file(fh, s_fname)                     # open
    
    # Write a simple test message
    t1.assign(counter, 1)
    t1.add(counter, 1)
    t1.str_store(s_content, "str_state_prefix")          # s11 = "STATE:"
    t1.write_to_file(fh, s_content)                      # write test
    t1.close_file(fh)                                    # close
    
    # Command polling: open command file for reading
    s_cmd_fname = 12
    s_cmd_content = 13
    t1.str_store(s_cmd_fname, "str_external_api_cmd_txt") # s12 = "external_api_cmd.txt"
    t1.open_read_file(fh, s_cmd_fname)                    # open_read
    t1.read_from_file(s_cmd_content, fh)                  # read a line -> s13
    t1.close_file(fh)                                     # close
    
    trigger1 = f"3.000000  {t1.num_ops()} {t1.compile()}"
    
    # ── Assemble triggers ──
    triggers = [trigger1]
    
    header = "simple_triggers_file version 1"
    count = str(len(triggers))
    
    return header + "\n" + count + "\n" + "\n".join(triggers) + "\n"


def build_strings():
    """Build strings.txt with our custom strings."""
    lines = ["stringsfile version 1"]
    for sid, sval in STRINGS.items():
        lines.append(f"{sid} {{!}}{sval}")
    return "\n".join(lines) + "\n"


def build_module_ini():
    """Build minimal module.ini."""
    return (
        "module_name = ExternalAPI\n"
        "compatible_with_warband = 1\n"
    )


def build_game_variables():
    """Build minimal game_variables.txt - just needed for module to load."""
    return (
        "variablesfile version 1\n"
        "counter = 0\n"
    )


def build_variables():
    """Build empty variables.txt."""
    return "variablesfile version 1\n"


def copy_native_files(output_dir):
    """Copy required .txt files from Native module."""
    required_files = [
        "actions.txt", "conversation.txt", "dialog_states.txt", 
        "factions.txt", "info_pages.txt", "item_kinds1.txt",
        "map_icons.txt", "map.txt", "menus.txt", "meshes.txt",
        "mission_templates.txt", "music.txt", "particle_systems.txt",
        "parties.txt", "party_templates.txt", "postfx.txt",
        "presentations.txt", "quests.txt", "quick_strings.txt",
        "scene_props.txt", "scenes.txt", "scripts.txt",
        "skills.txt", "skins.txt", "sounds.txt",
        "tableau_materials.txt", "tag_uses.txt", "triggers.txt",
        "troops.txt", "variable_uses.txt",
    ]
    
    for fname in required_files:
        src = NATIVE_DIR / fname
        dst = output_dir / fname
        if src.exists() and not dst.exists():
            shutil.copy2(str(src), str(dst))
            print(f"  Copied: {fname}")
        elif dst.exists():
            print(f"  Already exists: {fname}")
        else:
            print(f"  WARNING: {fname} not found in Native")


def main():
    parser = argparse.ArgumentParser(description="Build ExternalAPI module")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--from-native", action="store_true", 
                        help="Copy base files from Native module")
    args = parser.parse_args()
    
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    print(f"Building ExternalAPI module in: {output_dir}")
    
    # Copy base files from Native if needed
    if args.from_native or not list(output_dir.glob("*.txt")):
        if not NATIVE_DIR.exists():
            print(f"ERROR: Native module not found at {NATIVE_DIR}")
            sys.exit(1)
        print("\nCopying base files from Native...")
        copy_native_files(output_dir)
    
    # Generate our custom files
    print("\nGenerating module files...")
    
    # module.ini
    ini_path = output_dir / "module.ini"
    ini_path.write_text(build_module_ini())
    print(f"  Wrote: module.ini")
    
    # strings.txt
    strings_path = output_dir / "strings.txt"
    strings_path.write_text(build_strings())
    print(f"  Wrote: strings.txt")
    
    # simple_triggers.txt
    triggers_path = output_dir / "simple_triggers.txt"
    triggers_path.write_text(build_simple_triggers())
    print(f"  Wrote: simple_triggers.txt")
    
    # game_variables.txt
    gv_path = output_dir / "game_variables.txt"
    gv_path.write_text(build_game_variables())
    print(f"  Wrote: game_variables.txt")
    
    # variables.txt
    var_path = output_dir / "variables.txt"
    var_path.write_text(build_variables())
    print(f"  Wrote: variables.txt")
    
    print(f"\nDone! Module is at: {output_dir}")
    print(f"Symlink it to Modules/ if not already there:")
    print(f"  cd '{GAME_DIR}/Modules'")
    print(f"  ln -sf '{output_dir.resolve()}' ExternalAPI")


if __name__ == "__main__":
    main()
