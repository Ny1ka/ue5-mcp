"""Unreal Engine asset type registry — category definitions and classification engine.

Drives both filesystem heuristic scanning and Remote Control API result enrichment.
Add new categories here; all consumers pick them up automatically.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class AssetCategory:
    """Descriptor for one logical group of UE assets."""

    key: str
    display_name: str
    # UE class names that belong to this category (used when Remote Control returns class info).
    ue_class_names: frozenset[str]
    # Filename prefixes (e.g. "SM_", "MI_") for heuristic classification.
    name_prefixes: tuple[str, ...]
    # Content folder path segments that strongly suggest this category.
    folder_hints: tuple[str, ...]
    # File extensions beyond the default .uasset (e.g. ".umap" for World assets).
    extensions: tuple[str, ...] = (".uasset",)
    # Sort weight — lower = shown first in output.
    sort_order: int = 50

    def matches_class(self, ue_class: str) -> bool:
        return ue_class in self.ue_class_names

    def matches_prefix(self, asset_name: str) -> bool:
        upper = asset_name.upper()
        return any(upper.startswith(p.upper()) for p in self.name_prefixes)

    def matches_folder(self, path_parts: list[str]) -> bool:
        upper_parts = {p.upper() for p in path_parts}
        return any(hint.upper() in upper_parts for hint in self.folder_hints)


# ---------------------------------------------------------------------------
# Master category registry
# Order defines display_name sort fallback; sort_order field controls output.
# ---------------------------------------------------------------------------

ASSET_CATEGORIES: dict[str, AssetCategory] = {
    cat.key: cat
    for cat in [
        AssetCategory(
            key="maps",
            display_name="Maps / Levels",
            ue_class_names=frozenset({"World"}),
            name_prefixes=(),
            folder_hints=("Maps", "Levels", "Worlds"),
            extensions=(".umap", ".uasset"),
            sort_order=10,
        ),
        AssetCategory(
            key="blueprints",
            display_name="Blueprints",
            ue_class_names=frozenset({"Blueprint", "BlueprintGeneratedClass"}),
            name_prefixes=("BP_",),
            folder_hints=("Blueprints", "Actors", "Characters", "Gameplay", "Weapons", "Items"),
            sort_order=20,
        ),
        AssetCategory(
            key="anim_blueprints",
            display_name="Anim Blueprints",
            ue_class_names=frozenset({"AnimBlueprint"}),
            name_prefixes=("ABP_",),
            folder_hints=("Animations", "Anim", "AnimBP"),
            sort_order=21,
        ),
        AssetCategory(
            key="widget_blueprints",
            display_name="Widget Blueprints (UMG)",
            ue_class_names=frozenset({"WidgetBlueprint"}),
            name_prefixes=("WBP_", "UI_", "W_"),
            folder_hints=("UI", "UMG", "Widgets", "HUD", "Interface"),
            sort_order=22,
        ),
        AssetCategory(
            key="static_meshes",
            display_name="Static Meshes",
            ue_class_names=frozenset({"StaticMesh"}),
            name_prefixes=("SM_",),
            folder_hints=("Meshes", "StaticMeshes", "Props", "Architecture", "Environment", "Foliage"),
            sort_order=30,
        ),
        AssetCategory(
            key="skeletal_meshes",
            display_name="Skeletal Meshes",
            ue_class_names=frozenset({"SkeletalMesh"}),
            name_prefixes=("SK_",),
            folder_hints=("Characters", "SkeletalMeshes", "Creatures"),
            sort_order=31,
        ),
        AssetCategory(
            key="skeletons",
            display_name="Skeletons",
            ue_class_names=frozenset({"Skeleton"}),
            name_prefixes=("SKEL_",),
            folder_hints=("Skeletons", "Characters"),
            sort_order=32,
        ),
        AssetCategory(
            key="physics_assets",
            display_name="Physics Assets",
            ue_class_names=frozenset({"PhysicsAsset"}),
            name_prefixes=("PHYS_", "PA_", "PHY_"),
            folder_hints=("Physics", "Characters", "PhysicsAssets"),
            sort_order=33,
        ),
        AssetCategory(
            key="materials",
            display_name="Materials",
            ue_class_names=frozenset({"Material"}),
            name_prefixes=("M_",),
            folder_hints=("Materials",),
            sort_order=40,
        ),
        AssetCategory(
            key="material_instances",
            display_name="Material Instances",
            ue_class_names=frozenset({"MaterialInstanceConstant", "MaterialInstanceDynamic"}),
            name_prefixes=("MI_", "M_Inst", "MIC_"),
            folder_hints=("Materials", "MaterialInstances"),
            sort_order=41,
        ),
        AssetCategory(
            key="textures",
            display_name="Textures",
            ue_class_names=frozenset({
                "Texture2D", "TextureCube", "Texture2DArray",
                "VolumeTexture", "TextureRenderTarget2D", "TextureRenderTargetCube",
                "TextureLightProfile",
            }),
            name_prefixes=("T_", "TX_", "TEX_"),
            folder_hints=("Textures", "Texture"),
            sort_order=42,
        ),
        AssetCategory(
            key="niagara_systems",
            display_name="Niagara Systems",
            ue_class_names=frozenset({"NiagaraSystem"}),
            name_prefixes=("NS_", "FX_", "NFX_"),
            folder_hints=("Effects", "FX", "Niagara", "VFX"),
            sort_order=50,
        ),
        AssetCategory(
            key="niagara_emitters",
            display_name="Niagara Emitters",
            ue_class_names=frozenset({"NiagaraEmitter"}),
            name_prefixes=("NE_", "FXE_"),
            folder_hints=("Effects", "FX", "Niagara", "Emitters"),
            sort_order=51,
        ),
        AssetCategory(
            key="particle_systems",
            display_name="Particle Systems (Cascade)",
            ue_class_names=frozenset({"ParticleSystem"}),
            name_prefixes=("P_", "PS_"),
            folder_hints=("Particles", "Effects", "FX", "Cascade"),
            sort_order=52,
        ),
        AssetCategory(
            key="sound_waves",
            display_name="Sound Waves",
            ue_class_names=frozenset({"SoundWave", "SoundWaveProcedural"}),
            name_prefixes=("SW_", "SFX_"),
            folder_hints=("Audio", "Sounds", "SFX", "Music"),
            sort_order=60,
        ),
        AssetCategory(
            key="sound_cues",
            display_name="Sound Cues",
            ue_class_names=frozenset({"SoundCue"}),
            name_prefixes=("SC_", "S_Cue"),
            folder_hints=("Audio", "Sounds", "SFX"),
            sort_order=61,
        ),
        AssetCategory(
            key="meta_sounds",
            display_name="MetaSounds",
            ue_class_names=frozenset({"MetaSoundSource", "MetaSound"}),
            name_prefixes=("MSD_", "MS_", "MSS_"),
            folder_hints=("Audio", "MetaSounds", "Sounds"),
            sort_order=62,
        ),
        AssetCategory(
            key="sound_classes",
            display_name="Sound Classes & Mixes",
            ue_class_names=frozenset({"SoundClass", "SoundMix", "SoundAttenuation", "ReverbEffect"}),
            name_prefixes=("SCL_", "SMX_", "ATT_"),
            folder_hints=("Audio", "Sounds", "SoundClasses"),
            sort_order=63,
        ),
        AssetCategory(
            key="animations",
            display_name="Animations",
            ue_class_names=frozenset({
                "AnimSequence", "AnimMontage", "AnimComposite",
                "BlendSpace", "BlendSpace1D",
                "AimOffsetBlendSpace", "AimOffsetBlendSpace1D",
                "PoseAsset",
            }),
            name_prefixes=("A_", "Anim_", "AS_", "AM_", "BS_", "AO_"),
            folder_hints=("Animations", "Anim"),
            sort_order=70,
        ),
        AssetCategory(
            key="level_sequences",
            display_name="Level Sequences",
            ue_class_names=frozenset({"LevelSequence"}),
            name_prefixes=("LS_", "SEQ_", "Seq_"),
            folder_hints=("Cinematics", "Sequences", "Cutscenes", "LevelSequences"),
            sort_order=80,
        ),
        AssetCategory(
            key="data_tables",
            display_name="Data Tables",
            ue_class_names=frozenset({"DataTable"}),
            name_prefixes=("DT_",),
            folder_hints=("Data", "DataTables", "Tables"),
            sort_order=90,
        ),
        AssetCategory(
            key="data_assets",
            display_name="Data Assets",
            ue_class_names=frozenset({"DataAsset", "PrimaryDataAsset"}),
            name_prefixes=("DA_",),
            folder_hints=("Data", "DataAssets"),
            sort_order=91,
        ),
        AssetCategory(
            key="curves",
            display_name="Curves",
            ue_class_names=frozenset({
                "CurveFloat", "CurveVector", "CurveLinearColor",
                "CurveTable", "CurveLinearColorAtlas",
            }),
            name_prefixes=("Curve_", "CV_", "CRV_"),
            folder_hints=("Curves", "Data"),
            sort_order=92,
        ),
        AssetCategory(
            key="input",
            display_name="Input (Enhanced Input)",
            ue_class_names=frozenset({
                "InputAction", "InputMappingContext",
                "PlayerMappableInputConfig",
            }),
            name_prefixes=("IA_", "IMC_"),
            folder_hints=("Input", "EnhancedInput"),
            sort_order=100,
        ),
        AssetCategory(
            key="landscape",
            display_name="Landscape",
            ue_class_names=frozenset({
                "LandscapeLayerInfoObject", "LandscapeMaterialInstanceConstant",
                "LandscapeGrassType",
            }),
            name_prefixes=("LS_Grass_", "LG_", "LCI_"),
            folder_hints=("Landscape", "Terrain"),
            sort_order=110,
        ),
        AssetCategory(
            key="fonts",
            display_name="Fonts",
            ue_class_names=frozenset({"Font", "FontFace"}),
            name_prefixes=("Font_", "FNT_"),
            folder_hints=("Fonts", "UI", "UMG"),
            sort_order=120,
        ),
        AssetCategory(
            key="user_defined_structs",
            display_name="Structs & Enums",
            ue_class_names=frozenset({"UserDefinedStruct", "UserDefinedEnum"}),
            name_prefixes=("F_", "E_", "S_"),
            folder_hints=("Structs", "Enums", "Data", "Types"),
            sort_order=130,
        ),
    ]
}


# ---------------------------------------------------------------------------
# Classification engine
# ---------------------------------------------------------------------------

_PREFIX_INDEX: dict[str, str] = {}
_CLASS_INDEX: dict[str, str] = {}

for _cat in ASSET_CATEGORIES.values():
    for _prefix in _cat.name_prefixes:
        _PREFIX_INDEX[_prefix.upper()] = _cat.key
    for _cls in _cat.ue_class_names:
        _CLASS_INDEX[_cls] = _cat.key


def classify_by_class(ue_class: str) -> Optional[str]:
    """Return category key for a known UE class name, or None."""
    return _CLASS_INDEX.get(ue_class)


def classify_by_path(
    asset_name: str,
    path_parts: list[str],
    extension: str = ".uasset",
) -> str:
    """Heuristically classify an asset from its filename and folder path.

    Priority: extension → name prefix → folder hints → 'uncategorized'.
    """
    # Extension: .umap always means a World/Level asset
    if extension == ".umap":
        return "maps"

    # Prefix — longest match wins to handle "M_" vs "MI_" vs "MIC_"
    name_upper = asset_name.upper()
    best_key: Optional[str] = None
    best_len = 0
    for prefix_upper, key in _PREFIX_INDEX.items():
        if name_upper.startswith(prefix_upper) and len(prefix_upper) > best_len:
            best_key = key
            best_len = len(prefix_upper)
    if best_key:
        return best_key

    # Folder hints — collect all matching categories, pick lowest sort_order
    matches: list[AssetCategory] = []
    for cat in ASSET_CATEGORIES.values():
        if cat.matches_folder(path_parts):
            matches.append(cat)
    if matches:
        return min(matches, key=lambda c: c.sort_order).key

    return "uncategorized"


# ---------------------------------------------------------------------------
# Mock data factory — realistic stub for development without a live editor
# ---------------------------------------------------------------------------

MOCK_ASSETS: dict[str, list[dict]] = {
    "maps": [
        {"name": "MainMenu", "game_path": "/Game/Maps/MainMenu", "size_kb": 1024},
        {"name": "L_Dungeon_01", "game_path": "/Game/Maps/Dungeon/L_Dungeon_01", "size_kb": 8192},
        {"name": "L_OpenWorld", "game_path": "/Game/Maps/World/L_OpenWorld", "size_kb": 32768},
    ],
    "blueprints": [
        {"name": "BP_PlayerCharacter", "game_path": "/Game/Characters/BP_PlayerCharacter", "size_kb": 128},
        {"name": "BP_EnemyBase", "game_path": "/Game/Characters/Enemies/BP_EnemyBase", "size_kb": 96},
        {"name": "BP_Pistol", "game_path": "/Game/Weapons/BP_Pistol", "size_kb": 64},
        {"name": "BP_Rifle", "game_path": "/Game/Weapons/BP_Rifle", "size_kb": 72},
        {"name": "BP_Shotgun", "game_path": "/Game/Weapons/BP_Shotgun", "size_kb": 68},
        {"name": "BP_Door_Automatic", "game_path": "/Game/Interactables/BP_Door_Automatic", "size_kb": 48},
        {"name": "BP_GameMode_Main", "game_path": "/Game/Gameplay/BP_GameMode_Main", "size_kb": 32},
    ],
    "anim_blueprints": [
        {"name": "ABP_PlayerCharacter", "game_path": "/Game/Characters/ABP_PlayerCharacter", "size_kb": 112},
        {"name": "ABP_EnemyBase", "game_path": "/Game/Characters/Enemies/ABP_EnemyBase", "size_kb": 88},
    ],
    "widget_blueprints": [
        {"name": "WBP_HUD", "game_path": "/Game/UI/WBP_HUD", "size_kb": 56},
        {"name": "WBP_MainMenu", "game_path": "/Game/UI/WBP_MainMenu", "size_kb": 64},
        {"name": "WBP_InventoryScreen", "game_path": "/Game/UI/WBP_InventoryScreen", "size_kb": 80},
    ],
    "static_meshes": [
        {"name": "SM_Rock_01", "game_path": "/Game/Environment/Rocks/SM_Rock_01", "size_kb": 2048},
        {"name": "SM_Tree_Oak", "game_path": "/Game/Environment/Foliage/SM_Tree_Oak", "size_kb": 4096},
        {"name": "SM_Barrel", "game_path": "/Game/Props/SM_Barrel", "size_kb": 512},
        {"name": "SM_Crate_01", "game_path": "/Game/Props/SM_Crate_01", "size_kb": 384},
        {"name": "SM_Wall_Modular_01", "game_path": "/Game/Architecture/SM_Wall_Modular_01", "size_kb": 1024},
    ],
    "skeletal_meshes": [
        {"name": "SK_Mannequin", "game_path": "/Game/Characters/SK_Mannequin", "size_kb": 8192},
        {"name": "SK_Enemy_Zombie", "game_path": "/Game/Characters/Enemies/SK_Enemy_Zombie", "size_kb": 6144},
    ],
    "materials": [
        {"name": "M_Rock", "game_path": "/Game/Materials/M_Rock", "size_kb": 64},
        {"name": "M_Character_Base", "game_path": "/Game/Materials/M_Character_Base", "size_kb": 128},
        {"name": "M_Master_PBR", "game_path": "/Game/Materials/M_Master_PBR", "size_kb": 96},
    ],
    "material_instances": [
        {"name": "MI_Rock_Mossy", "game_path": "/Game/Materials/MI_Rock_Mossy", "size_kb": 16},
        {"name": "MI_Player_Default", "game_path": "/Game/Materials/MI_Player_Default", "size_kb": 16},
        {"name": "MI_Enemy_Zombie", "game_path": "/Game/Materials/MI_Enemy_Zombie", "size_kb": 16},
    ],
    "textures": [
        {"name": "T_Rock_BaseColor", "game_path": "/Game/Textures/T_Rock_BaseColor", "size_kb": 4096},
        {"name": "T_Rock_Normal", "game_path": "/Game/Textures/T_Rock_Normal", "size_kb": 4096},
        {"name": "T_Character_Skin_D", "game_path": "/Game/Textures/Characters/T_Character_Skin_D", "size_kb": 8192},
    ],
    "niagara_systems": [
        {"name": "NS_Fire", "game_path": "/Game/Effects/NS_Fire", "size_kb": 256},
        {"name": "NS_Explosion", "game_path": "/Game/Effects/NS_Explosion", "size_kb": 384},
        {"name": "NS_MuzzleFlash", "game_path": "/Game/Weapons/Effects/NS_MuzzleFlash", "size_kb": 128},
    ],
    "sound_waves": [
        {"name": "SW_Gunshot_Pistol", "game_path": "/Game/Audio/SFX/SW_Gunshot_Pistol", "size_kb": 512},
        {"name": "SW_Footstep_Concrete", "game_path": "/Game/Audio/SFX/SW_Footstep_Concrete", "size_kb": 256},
    ],
    "sound_cues": [
        {"name": "SC_Weapon_Pistol", "game_path": "/Game/Audio/SFX/SC_Weapon_Pistol", "size_kb": 32},
        {"name": "SC_Ambience_Forest", "game_path": "/Game/Audio/Ambience/SC_Ambience_Forest", "size_kb": 48},
    ],
    "animations": [
        {"name": "A_Idle", "game_path": "/Game/Characters/Animations/A_Idle", "size_kb": 192},
        {"name": "A_Run_Forward", "game_path": "/Game/Characters/Animations/A_Run_Forward", "size_kb": 256},
        {"name": "A_Jump_Start", "game_path": "/Game/Characters/Animations/A_Jump_Start", "size_kb": 128},
    ],
    "data_tables": [
        {"name": "DT_WeaponStats", "game_path": "/Game/Data/DT_WeaponStats", "size_kb": 8},
        {"name": "DT_EnemyStats", "game_path": "/Game/Data/DT_EnemyStats", "size_kb": 12},
    ],
    "input": [
        {"name": "IA_Jump", "game_path": "/Game/Input/IA_Jump", "size_kb": 4},
        {"name": "IA_Move", "game_path": "/Game/Input/IA_Move", "size_kb": 4},
        {"name": "IMC_Default", "game_path": "/Game/Input/IMC_Default", "size_kb": 8},
    ],
}
