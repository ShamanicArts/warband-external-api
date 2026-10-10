"""Bounded declarations for trusted Module System extension operations."""

import re
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType

_OPERATION_NAME = re.compile(r"^[a-z][a-z0-9]*(?:[.-][a-z0-9][a-z0-9-]*)+$")
_ARGUMENT_NAME = re.compile(r"^[a-z][a-z0-9_]*$")
_HANDLER_ARITY = MappingProxyType(
    {
        "troop_add_gold": 2,
        "troop_remove_gold": 2,
    }
)


class CompiledContext(StrEnum):
    """Engine context in which an operation may execute."""

    CAMPAIGN = "campaign"
    MENU = "menu"
    MISSION = "mission"


class HandlerOperand(StrEnum):
    """Symbolic values resolved to guarded callback locals during compilation."""

    ARG0 = "arg0"
    ARG1 = "arg1"
    ARG2 = "arg2"
    PLAYER_TROOP = "player_troop"


@dataclass(frozen=True, slots=True)
class CompiledIntegerArgument:
    """One exact, bounded integer carried over the engine HTTP protocol."""

    name: str
    minimum: int
    maximum: int

    def __post_init__(self):
        if not isinstance(self.name, str) or not _ARGUMENT_NAME.fullmatch(self.name):
            raise ValueError("compiled argument name must be a lowercase identifier")
        if type(self.minimum) is not int or type(self.maximum) is not int:
            raise TypeError("compiled argument bounds must be integers")
        if self.minimum > self.maximum:
            raise ValueError("compiled argument bounds are inverted")
        if self.minimum < -(2**31) or self.maximum > 2**31 - 1:
            raise ValueError("compiled argument bounds must fit signed 32-bit integers")

    def validate(self, value):
        if type(value) is not int or not self.minimum <= value <= self.maximum:
            raise ValueError(
                f"compiled argument {self.name!r} must be an integer in "
                f"[{self.minimum}, {self.maximum}]"
            )
        return value

    def manifest(self):
        return {
            "name": self.name,
            "type": "integer",
            "minimum": self.minimum,
            "maximum": self.maximum,
        }


@dataclass(frozen=True, slots=True)
class CompiledInstruction:
    """One allowlisted Module System instruction in an extension handler."""

    operation: str
    operands: tuple[int | HandlerOperand, ...]

    def __post_init__(self):
        if self.operation not in _HANDLER_ARITY:
            raise ValueError(
                f"compiled handler operation {self.operation!r} is not safe"
            )
        operands = tuple(self.operands)
        if len(operands) != _HANDLER_ARITY[self.operation]:
            raise ValueError(
                f"compiled handler operation {self.operation!r} requires "
                f"{_HANDLER_ARITY[self.operation]} operands"
            )
        for operand in operands:
            if isinstance(operand, HandlerOperand):
                continue
            if type(operand) is not int or not -(2**31) <= operand <= 2**31 - 1:
                raise ValueError(
                    "compiled handler operands must be symbolic values or signed "
                    "32-bit integer literals"
                )
        object.__setattr__(self, "operands", operands)

    def manifest(self):
        return {
            "operation": self.operation,
            "operands": [
                operand.value if isinstance(operand, HandlerOperand) else operand
                for operand in self.operands
            ],
        }


@dataclass(frozen=True, slots=True)
class CompiledOperation:
    """A validated bridge command and its statically compiled engine handler."""

    name: str
    opcode: int
    context: CompiledContext
    arguments: tuple[CompiledIntegerArgument, ...]
    handler: tuple[CompiledInstruction, ...]
    integration_revision: int = 16

    def __post_init__(self):
        if not isinstance(self.name, str) or not _OPERATION_NAME.fullmatch(self.name):
            raise ValueError("compiled operation name must be a namespaced identifier")
        if type(self.opcode) is not int or not 1000 <= self.opcode <= 9999:
            raise ValueError(
                "compiled operation opcode must be in the reserved 1000-9999 range"
            )
        if not isinstance(self.context, CompiledContext):
            raise TypeError("compiled operation context must be CompiledContext")
        if type(self.integration_revision) is not int or self.integration_revision < 0:
            raise ValueError("compiled operation integration revision is invalid")
        arguments = tuple(self.arguments)
        if len(arguments) > 3 or any(
            not isinstance(argument, CompiledIntegerArgument) for argument in arguments
        ):
            raise TypeError(
                "compiled operation arguments must contain at most three "
                "CompiledIntegerArgument values"
            )
        names = [argument.name for argument in arguments]
        if len(names) != len(set(names)):
            raise ValueError("compiled operation argument names must be unique")
        object.__setattr__(self, "arguments", arguments)
        handler = tuple(self.handler)
        if not 1 <= len(handler) <= 32 or any(
            not isinstance(instruction, CompiledInstruction) for instruction in handler
        ):
            raise TypeError(
                "compiled operation handler must contain 1-32 "
                "CompiledInstruction values"
            )
        available = {HandlerOperand(f"arg{index}") for index in range(len(arguments))}
        for instruction in handler:
            unavailable = {
                operand
                for operand in instruction.operands
                if isinstance(operand, HandlerOperand)
                and operand is not HandlerOperand.PLAYER_TROOP
                and operand not in available
            }
            if unavailable:
                raise ValueError("compiled handler references an undeclared argument")
        object.__setattr__(self, "handler", handler)

    def validate(self, payload, state):
        if not isinstance(payload, dict) or set(payload) != {
            argument.name for argument in self.arguments
        }:
            raise ValueError("Unexpected or missing compiled operation arguments")
        if not state.get("connected"):
            raise ValueError("Game telemetry is stale or disconnected")
        if state.get("protocol") != 2 or state.get("context") != self.context.value:
            raise ValueError(
                f"This operation requires protocol-2 {self.context.value} telemetry"
            )
        if state.get("integration_revision") != self.integration_revision:
            raise ValueError(
                "This operation requires integration revision "
                f"{self.integration_revision}"
            )
        for argument in self.arguments:
            argument.validate(payload[argument.name])

    def wire_arguments(self, payload):
        values = [
            argument.validate(payload[argument.name]) for argument in self.arguments
        ]
        return [*values, *([0] * (4 - len(values)))]

    def manifest(self):
        return {
            "name": self.name,
            "opcode": self.opcode,
            "context": self.context.value,
            "integration_revision": self.integration_revision,
            "arguments": [argument.manifest() for argument in self.arguments],
            "handler": [instruction.manifest() for instruction in self.handler],
        }


def index_compiled_operations(operations, *, reserved_names=(), reserved_opcodes=()):
    """Validate a declaration set and return an immutable name index."""

    result = {}
    opcodes = set(reserved_opcodes)
    reserved_names = set(reserved_names)
    for operation in tuple(operations):
        if not isinstance(operation, CompiledOperation):
            raise TypeError("compiled operations must contain CompiledOperation values")
        if operation.name in reserved_names or operation.name in result:
            raise ValueError(f"compiled operation name {operation.name!r} collides")
        if operation.opcode in opcodes:
            raise ValueError(f"compiled operation opcode {operation.opcode} collides")
        result[operation.name] = operation
        opcodes.add(operation.opcode)
    return MappingProxyType(result)
