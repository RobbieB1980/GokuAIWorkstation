# Migration stage order

Inventory → build skeleton → mappings → registration → utilities → blocks/items → block entities → entities → networking → rendering → worldgen/data → assets/models/animations/sounds → datagen → compilation repair → client launch → server launch → behaviour validation → final report.

Validate with destination-Java builds between stages when errors accumulate; do not batch hundreds of unrelated edits.
