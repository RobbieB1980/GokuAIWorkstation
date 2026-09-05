# 262r shard/converter index (links only)

Do **not** paste shard bodies into skills or AGENTS. Open **one** file under `C:\gokuai\Data\262r\`.

## Converter notes

| ID | File | Summary |
|---|---|---|
| `mc-262r-dep-dual-pull` | `converter/dual-deps.md` | Pull source-version + 26.2 Modrinth jars (libs-source + libs) |
| `mc-262r-dep-source-version` | `converter/dual-deps.md` | Convert fallback uses detected SourceMinecraftVersion, not hardcoded 1.20.1 |
| `mc-262r-dep-import-detect` | `converter/import-detect.md` | Import scan SimpleMatch without regex Escape |
| `mc-262r-soft-dep-exclude` | `converter/soft-dep-exclude.md` | Exclude soft integrations only when libs/ has no matching jar |
| `mc-262r-soft-dep-keep-when-jar` | `converter/soft-dep-exclude.md` | Keep compat/jei when jei-26.2 jar present |
| `mc-262r-fix-in-grok-promptfile` | `converter/fix-in-grok.md` | Start-GokuAI PromptFile single-line pointer; no multiline bat |
| `mc-262r-fix-in-grok-path` | `converter/fix-in-grok.md` | GROK_REPAIR_PROMPT.md must name FAILED OUTPUT FOLDER |
| `mc-262r-itemhandler-block-stub` | `converter/capability-stub.md` | Multiline ItemHandler.BLOCK registerBlockEntity stub; no orphan ); |
| `mc-262r-destination-java` | `converter/destination-java.md` | Installer -Compile always uses destination JDK 25; org.gradle.java.home pin |

## Shards

| ID | File | Summary |
|---|---|---|
| `mc-262r-feline-minecart-packages` | `shards/feline-minecart-packages.md` | FelineModel→Adult/Baby/Abstract split; minecart/boat packages; mixin slash descriptors + this instanceof |
| `mc-262r-value-io-be` | `shards/value-io.md` | BlockEntity save/load ValueInput/Output |
| `mc-262r-value-io-entity-load` | `shards/value-io.md` | Entity.load(TagValueInput); not protected readAdditionalSaveData |
| `mc-262r-map-entry-getkey` | `shards/map-entry-accessors.md` | Map.Entry property/value â†’ getKey/getValue |
| `mc-262r-entitytype-bystring` | `shards/entity-type-lookup.md` | EntityType.byString â†’ BuiltInRegistries.ENTITY_TYPE.getOptional |
| `mc-262r-flying-mob-removed` | `shards/flying-mob-removed.md` | FlyingMob/FlyingAnimal removed; use Ghast/Phantom/Bee.isFlying |
| `mc-262r-ber-render-state` | `shards/block-entity-render-state.md` | BlockEntityRenderer<T,S> create/extract/submit |
| `mc-262r-tooltip-consumer` | `shards/tooltip-consumer.md` | appendHoverText Consumer.accept; GuiGraphicsExtractor setTooltip* |
| `mc-262r-customdata-copytag` | `shards/misc-26.2-leaf.md` | CustomData.getUnsafe â†’ copyTag |
| `mc-262r-compound-getstring-or` | `shards/misc-26.2-leaf.md` | CompoundTag.getString â†’ getStringOr for String assign |
| `mc-262r-resourcekey-identifier` | `shards/misc-26.2-leaf.md` | ResourceKey.location â†’ identifier |
| `mc-262r-spawnegg-gettype` | `shards/misc-26.2-leaf.md` | SpawnEggItem.getType(ItemStack) static |
| `mc-262r-oncraftedby` | `shards/misc-26.2-leaf.md` | onCraftedBy(stack, Player) |
| `mc-262r-hurtandbreak-hand` | `shards/misc-26.2-leaf.md` | hurtAndBreak(n, living, InteractionHand) |
| `mc-262r-villagerdata-type` | `shards/misc-26.2-leaf.md` | VillagerData.type()/profession() Holders + ResourceKey compare |
| `mc-262r-cat-frog-variants` | `shards/misc-26.2-leaf.md` | CatVariants / FrogVariants ResourceKeys |
| `mc-262r-cubemob-package` | `shards/misc-26.2-leaf.md` | Slime/MagmaCube â†’ monster.cubemob |
| `mc-262r-select-item-valuecodec` | `shards/misc-26.2-leaf.md` | SelectItemModelProperty<T> + valueCodec |
| `mc-262r-datacomponent-builder-generic` | `shards/misc-26.2-leaf.md` | DataComponentType.<T>builder() |
| `mc-262r-screen-extract` | `shards/misc-26.2-leaf.md` | Screen extractBackground / extractRenderState |
| `mc-262r-serverplayer-level` | `shards/misc-26.2-leaf.md` | serverPlayer.serverLevel â†’ level() |
| `mc-262r-mod-version-placeholder` | `shards/misc-26.2-leaf.md` | Strip ${file.jarVersion} from mod_version |
| `mc-262r-advancements-stoplistening` | `shards/misc-26.2-leaf.md` | Remove PlayerAdvancements.stopListening |
| `mc-262r-itemstack-components-bound` | `shards/itemstack-components-bound.md` | No ItemStack in static/FMLClientSetup; string defaults + lazy ensureRegistered |
| `mc-262r-gui-preview-entity-id` | `crashes.md` | GUI preview Entity.setId before InventoryScreen extract; INVALID_ENTITY_ID=0 throws |
| `mc-262r-modlauncher-fmlloader` | `shards/misc-26.2-leaf.md` | Launcher.INSTANCE VERSION probe → FMLLoader.isProduction |
| `mc-262r-item-props-ctor-dedupe` | `shards/misc-26.2-leaf.md` | Skip/collapse duplicate Item.Properties constructors |
| `mc-262r-gametest-always-exclude` | `converter/soft-dep-exclude.md` | Always exclude **/gametest/** in build.gradle |

Ledger files: `INDEX.md`, `remaps.md`, `crashes.md`, `do-not.md`, `pipeline.md`.
