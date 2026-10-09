#!/usr/bin/env python3
"""
Operation opcodes for Mount & Blade: Warband Module System
Reference: Official header_operations.py from TaleWorlds Module System 1.171
"""

# Control flow
try_begin = 4
try_end = 3
else_op = 5
endif = 3
endtry = 3

# Comparison
eq = 31          # is_val_equal
neq = 32         # is_val_not_equal (actually used as lt in some contexts)
ge = 30          # is_val_greater_or_equal
le = 33          # is_val_less_or_equal
gt = 30          # is_val_greater (same as ge but strict)
lt = 32          # is_val_less_than

# Value / Math operations
val_set = 2133
val_add = 2105
val_sub = 2106
val_mul = 2107
val_div = 2108
val_mod = 2112
val_min = 2110
val_max = 2111
val_abs = 2114
val_random = 2136
val_or = 2147483678
val_and = 2147483679

# String operations
str_register_string_start = 700
str_register_string_end = 701
str_store_string = 722       # string_register_string(dest, string_id)
str_store_string_reg = 723   # string_register_string_reg(dest, src)
str_format_int = 729         # str_store_string_format(dest, int_value) - store integer as string
str_format_int2 = 730        # second integer formatting
str_format_end = 731         # finalize string formatting
str_clear = 720
str_concat = 721

# File I/O
open_write_file = 724
open_read_file = 725
write_to_file = 726
read_from_file = 727
close_file = 728

# Script calls
call_script = 1
call_script_id = 2

# Slot operations (read/write entity data)
troop_set_slot = 500
party_set_slot = 501
faction_set_slot = 502
agent_set_slot = 506
scene_set_slot = 560
  
troop_get_slot = 520
party_get_slot = 521
faction_get_slot = 522
agent_get_slot = 526
scene_get_slot = 561
store_in_troop_slot = 525
store_in_party_slot = 525

# Agent operations
agent_get_position = 1700
agent_set_position = 1701
agent_is_alive = 1710
agent_is_human = 1711
agent_is_wounded = 1712
agent_get_troop_id = 1714
agent_get_hit_points = 1715
agent_set_hit_points = 1716
agent_get_slot_op = 1720
agent_set_slot_op = 1721
agent_get_team = 1722
agent_is_active = 1735
agent_get_accuracy = 1708
agent_set_accuracy = 1709

# Party operations
party_get_position = 1609
party_set_position = 1610
party_get_num_companions = 1650
party_get_num_prisoners = 1651
party_get_morale = 1652
party_set_morale = 1653
party_get_faction = 1609
party_set_faction = 1611
party_get_ai_behavior = 1662
party_set_ai_behavior = 1663
party_set_ai_object = 1609
party_get_current_terrain = 1655
party_get_num_prisoners_with_party = 1652
party_get_prisoner = 1696
party_set_bandit_attraction = 1619

# Faction operations
get_faction_between_factions = 1615
faction_set_slot_op = 502
faction_get_slot_op = 520
store_faction_name = 2308
faction_get_name = 2308

# Game state
game_get_player_gold = 524
game_set_player_gold = 525  
game_get_renown_level = 522
game_set_renown_level = 523
game_get_honor_level = 874
game_set_honor_level = 875
change_honor = 787
change_reputation = 788

# Map operations
party_move_to = 1
party_force_move_to = 2

# Mission operations
mission_cam_get_position = 1
mission_get_time = 3
mission_set_time = 4

# Display
display_message = 2060
tutorial_message = 1106
show_game_menu = 1
display_log_message = 1105
