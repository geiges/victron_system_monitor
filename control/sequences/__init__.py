from control.sequences.wallbox_on import WallboxOnSequence
from control.sequences.wallbox_off import WallboxOffSequence

SEQUENCES: dict[str, type] = {
    "wallbox_on": WallboxOnSequence,
    "wallbox_off": WallboxOffSequence,
}
