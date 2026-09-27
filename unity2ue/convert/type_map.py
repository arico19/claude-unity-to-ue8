"""Mapeo de tipos C#/Unity -> C++/Unreal Engine."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# Tipo C# -> (tipo C++, admite UPROPERTY, include)
VALUE_TYPES: dict[str, tuple[str, bool, str | None]] = {
    "float": ("float", True, None),
    "Single": ("float", True, None),
    "double": ("double", True, None),
    "int": ("int32", True, None),
    "Int32": ("int32", True, None),
    "uint": ("uint32", True, None),
    "long": ("int64", True, None),
    "ulong": ("uint64", True, None),
    "short": ("int16", True, None),
    "ushort": ("uint16", True, None),
    "byte": ("uint8", True, None),
    "sbyte": ("int8", True, None),
    "bool": ("bool", True, None),
    "Boolean": ("bool", True, None),
    "string": ("FString", True, None),
    "String": ("FString", True, None),
    "char": ("FString", True, None),
    "object": ("UObject*", False, None),
    "void": ("void", True, None),
    "Vector3": ("FVector", True, None),
    "Vector3Int": ("FIntVector", True, None),
    "Vector2": ("FVector2D", True, None),
    "Vector2Int": ("FIntPoint", True, None),
    "Vector4": ("FVector4", True, None),
    "Quaternion": ("FQuat", True, None),
    "Color": ("FLinearColor", True, None),
    "Color32": ("FColor", True, None),
    "Rect": ("FBox2D", True, None),
    "Bounds": ("FBox", True, None),
    "Matrix4x4": ("FMatrix", True, None),
    "Ray": ("FRay", False, None),
    "RaycastHit": ("FHitResult", True, None),
    "Collision": ("FHitResult", True, None),
    "AnimationCurve": ("FRuntimeFloatCurve", True, "Curves/CurveFloat.h"),
    "KeyCode": ("FKey", True, "InputCoreTypes.h"),
    "LayerMask": ("int32", True, None),  # máscara de capas: revisar -> canales de colisión
    "Space": ("bool", True, None),
    "ForceMode": ("uint8", True, None),
    "TimeSpan": ("FTimespan", True, None),
    "DateTime": ("FDateTime", True, None),
    "UnityEvent": ("FUnityEvent", True, "UnityCompat/UnityBehaviour.h"),
    "Action": ("FSimpleDelegate", False, None),
}

# Tipo UnityEngine.Object -> (clase UE, include)
OBJECT_TYPES: dict[str, tuple[str, str]] = {
    "GameObject": ("AActor", "GameFramework/Actor.h"),
    "Transform": ("USceneComponent", "Components/SceneComponent.h"),
    "RectTransform": ("UWidget", "Components/Widget.h"),
    "Component": ("UActorComponent", "Components/ActorComponent.h"),
    "Behaviour": ("UActorComponent", "Components/ActorComponent.h"),
    "MonoBehaviour": ("UActorComponent", "Components/ActorComponent.h"),
    "Rigidbody": ("UPrimitiveComponent", "Components/PrimitiveComponent.h"),
    "Rigidbody2D": ("UPrimitiveComponent", "Components/PrimitiveComponent.h"),
    "Collider": ("UPrimitiveComponent", "Components/PrimitiveComponent.h"),
    "BoxCollider": ("UBoxComponent", "Components/BoxComponent.h"),
    "SphereCollider": ("USphereComponent", "Components/SphereComponent.h"),
    "CapsuleCollider": ("UCapsuleComponent", "Components/CapsuleComponent.h"),
    "Collider2D": ("UPrimitiveComponent", "Components/PrimitiveComponent.h"),
    "CharacterController": ("UCharacterMovementComponent", "GameFramework/CharacterMovementComponent.h"),
    "Camera": ("UCameraComponent", "Camera/CameraComponent.h"),
    "Light": ("ULightComponent", "Components/LightComponent.h"),
    "AudioSource": ("UAudioComponent", "Components/AudioComponent.h"),
    "AudioClip": ("USoundBase", "Sound/SoundBase.h"),
    "AudioMixer": ("USoundMix", "Sound/SoundMix.h"),
    "Material": ("UMaterialInterface", "Materials/MaterialInterface.h"),
    "PhysicMaterial": ("UPhysicalMaterial", "PhysicalMaterials/PhysicalMaterial.h"),
    "Texture": ("UTexture", "Engine/Texture.h"),
    "Texture2D": ("UTexture2D", "Engine/Texture2D.h"),
    "RenderTexture": ("UTextureRenderTarget2D", "Engine/TextureRenderTarget2D.h"),
    "Sprite": ("UObject", "UObject/Object.h"),  # UPaperSprite (plugin Paper2D)
    "Mesh": ("UStaticMesh", "Engine/StaticMesh.h"),
    "MeshFilter": ("UStaticMeshComponent", "Components/StaticMeshComponent.h"),
    "MeshRenderer": ("UStaticMeshComponent", "Components/StaticMeshComponent.h"),
    "Renderer": ("UPrimitiveComponent", "Components/PrimitiveComponent.h"),
    "SkinnedMeshRenderer": ("USkeletalMeshComponent", "Components/SkeletalMeshComponent.h"),
    "Animator": ("USkeletalMeshComponent", "Components/SkeletalMeshComponent.h"),
    "Animation": ("USkeletalMeshComponent", "Components/SkeletalMeshComponent.h"),
    "AnimationClip": ("UAnimSequence", "Animation/AnimSequence.h"),
    "ParticleSystem": ("UNiagaraComponent", "NiagaraComponent.h"),
    "ScriptableObject": ("UDataAsset", "Engine/DataAsset.h"),
    "Shader": ("UMaterialInterface", "Materials/MaterialInterface.h"),
    "Font": ("UFont", "Engine/Font.h"),
    "Canvas": ("UUserWidget", "Blueprint/UserWidget.h"),
    "Text": ("UTextBlock", "Components/TextBlock.h"),
    "TMP_Text": ("UTextBlock", "Components/TextBlock.h"),
    "TextMeshProUGUI": ("UTextBlock", "Components/TextBlock.h"),
    "TextMeshPro": ("UTextRenderComponent", "Components/TextRenderComponent.h"),
    "Image": ("UImage", "Components/Image.h"),
    "RawImage": ("UImage", "Components/Image.h"),
    "Button": ("UButton", "Components/Button.h"),
    "Slider": ("USlider", "Components/Slider.h"),
    "Toggle": ("UCheckBox", "Components/CheckBox.h"),
    "InputField": ("UEditableTextBox", "Components/EditableTextBox.h"),
    "TMP_InputField": ("UEditableTextBox", "Components/EditableTextBox.h"),
    "NavMeshAgent": ("UPathFollowingComponent", "Navigation/PathFollowingComponent.h"),
    "InputAction": ("UInputAction", "InputAction.h"),
    "InputActionReference": ("UInputAction", "InputAction.h"),
    "Object": ("UObject", "UObject/Object.h"),
}
# Tipos que en Unity se usan como "plantilla a instanciar" (prefab) -> clase
PREFAB_HINT = re.compile(r"prefab|template|spawn", re.I)

CONTAINERS = {
    "List": "TArray", "IList": "TArray", "IEnumerable": "TArray", "Queue": "TArray", "Stack": "TArray",
    "HashSet": "TSet", "Dictionary": "TMap", "IDictionary": "TMap",
}


@dataclass
class CppType:
    decl: str  # declaración para campo/propiedad
    param: str  # declaración para parámetro/retorno
    uproperty: bool = True
    includes: set[str] = field(default_factory=set)
    forward: set[str] = field(default_factory=set)
    note: str | None = None
    is_object: bool = False


@dataclass
class ProjectType:
    kind: str  # component | data_asset | struct | enum | object | interface | library
    cpp_name: str  # con prefijo (UFoo, FBar, EBaz)
    header: str | None = None  # include relativo, p.ej. "Unity/Foo.h"
    cs_type: object = field(default=None, compare=False, repr=False)  # CSType de origen (herencia)


class TypeMapper:
    def __init__(self, project_types: dict[str, ProjectType] | None = None) -> None:
        self.project_types = project_types or {}

    def map(self, cs_type: str, field_name: str = "") -> CppType:
        t = re.sub(r"\s+", "", cs_type.strip())
        t = re.sub(r"^(global::)?(UnityEngine|System|System\.Collections\.Generic|TMPro|UnityEngine\.UI)\.", "", t)
        nullable = t.endswith("?")
        t = t.rstrip("?")
        # Arrays T[] / T[,]
        m = re.fullmatch(r"(.+)\[,*\]", t)
        if m:
            inner = self.map(m.group(1), field_name)
            return self._container("TArray", [inner], inner.note)
        m = re.fullmatch(r"([\w.]+)<(.+)>", t)
        if m:
            base = m.group(1).split(".")[-1]
            args = [a for a in _split_generic(m.group(2))]
            if base in CONTAINERS:
                inner = [self.map(a, field_name) for a in args]
                return self._container(CONTAINERS[base], inner, None)
            if base in ("UnityEvent", "Action", "Func"):
                return CppType("FUnityEvent", "FUnityEvent", True, {"UnityCompat/UnityBehaviour.h"},
                               note=f"{cs_type}: evento con parámetros -> declarar un delegate dinámico propio")
            return CppType("int32", "int32", False, note=f"Tipo genérico no mapeado: {cs_type}")
        name = t.split(".")[-1]
        if name in VALUE_TYPES:
            decl, ok, inc = VALUE_TYPES[name]
            ct = CppType(decl, decl, ok, {inc} if inc else set())
            if nullable:
                ct.note = f"{cs_type}: nullable -> usar TOptional si hace falta"
            return ct
        if name in self.project_types:
            pt = self.project_types[name]
            if pt.kind in ("struct", "enum"):
                inc = {pt.header} if pt.header else set()
                return CppType(pt.cpp_name, pt.cpp_name, True, inc)
            if pt.kind == "interface":
                return CppType(f"TScriptInterface<{pt.cpp_name.replace('U', 'I', 1)}>",
                               f"TScriptInterface<{pt.cpp_name.replace('U', 'I', 1)}>", True,
                               {pt.header} if pt.header else set())
            if pt.kind == "component" and PREFAB_HINT.search(field_name or ""):
                # `Man manPrefab` en Unity apunta a un prefab: en UE es el Blueprint a spawnear;
                # el componente se obtiene del actor creado (FindComponentByClass<UMan>()).
                return CppType("TSubclassOf<AActor>", "TSubclassOf<AActor>", True, {"GameFramework/Actor.h"},
                               note=f"{name} usado como prefab -> TSubclassOf<AActor>; tras SpawnActor usar "
                                    f"FindComponentByClass<{pt.cpp_name}>()")
            return CppType(f"TObjectPtr<{pt.cpp_name}>", f"{pt.cpp_name}*", True, set(), {pt.cpp_name},
                           is_object=True)
        if name in OBJECT_TYPES:
            cls, inc = OBJECT_TYPES[name]
            is_scene_type = name in ("GameObject", "Transform") or cls.endswith("Component") or cls.startswith("A")
            if is_scene_type and PREFAB_HINT.search(field_name or ""):
                return CppType("TSubclassOf<AActor>", "TSubclassOf<AActor>", True, {"GameFramework/Actor.h"},
                               note=f"{name} usado como prefab -> TSubclassOf<AActor> (Blueprint)")
            note = None
            if name == "Sprite":
                note = "Sprite -> UPaperSprite (activar plugin Paper2D y cambiar el tipo)"
            return CppType(f"TObjectPtr<{cls}>", f"{cls}*", True, {inc}, is_object=True, note=note)
        return CppType("int32", "int32", False, note=f"Tipo no mapeado: {cs_type}")

    @staticmethod
    def _container(kind: str, inner: list[CppType], note: str | None) -> CppType:
        includes: set[str] = set()
        forward: set[str] = set()
        ok = True
        for i in inner:
            includes |= i.includes
            forward |= i.forward
            ok = ok and i.uproperty and not i.decl.startswith(("TArray", "TMap", "TSet"))
        args = ", ".join(i.decl for i in inner)
        decl = f"{kind}<{args}>"
        return CppType(decl, f"const {decl}&", ok, includes, forward,
                       note=note or next((i.note for i in inner if i.note), None))


def _split_generic(text: str) -> list[str]:
    parts, depth, cur = [], 0, ""
    for ch in text:
        if ch == "<":
            depth += 1
        elif ch == ">":
            depth -= 1
        if ch == "," and depth == 0:
            parts.append(cur)
            cur = ""
        else:
            cur += ch
    parts.append(cur)
    return [p.strip() for p in parts if p.strip()]


_FLOAT_LIT = re.compile(r"^([+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?)[fFdDmM]?$")
_INT_LIT = re.compile(r"^[+-]?\d+[uUlL]*$")
_UNITY_CONSTS = {
    "Vector3.zero": "FVector::ZeroVector", "Vector3.one": "FVector::OneVector",
    "Vector3.up": "FVector::UpVector", "Vector3.down": "FVector::DownVector",
    "Vector3.forward": "FVector::ForwardVector", "Vector3.back": "FVector::BackwardVector",
    "Vector3.right": "FVector::RightVector", "Vector3.left": "FVector::LeftVector",
    "Vector2.zero": "FVector2D::ZeroVector", "Vector2.one": "FVector2D(1.0, 1.0)",
    "Quaternion.identity": "FQuat::Identity",
    "Color.white": "FLinearColor::White", "Color.black": "FLinearColor::Black",
    "Color.red": "FLinearColor::Red", "Color.green": "FLinearColor::Green",
    "Color.blue": "FLinearColor::Blue", "Color.yellow": "FLinearColor::Yellow",
    "Color.clear": "FLinearColor::Transparent", "Color.gray": "FLinearColor::Gray",
    "Color.grey": "FLinearColor::Gray",
    "null": "nullptr", "true": "true", "false": "false",
    "string.Empty": "FString()", "String.Empty": "FString()",
    "KeyCode.Space": "EKeys::SpaceBar", "KeyCode.Return": "EKeys::Enter", "KeyCode.Escape": "EKeys::Escape",
}


def cpp_default(value: str | None, ctype: CppType, project_types: dict[str, ProjectType]) -> str | None:
    """Traduce un inicializador C# sencillo a C++. Devuelve None si no es trivial."""
    if value is None:
        return None
    v = value.strip()
    if v in _UNITY_CONSTS:
        out = _UNITY_CONSTS[v]
        if out == "nullptr" and not ctype.is_object:
            return None
        return out
    m = _FLOAT_LIT.match(v)
    if m and ctype.decl in ("float", "double"):
        num = m.group(1)
        if ctype.decl == "float":
            return num + ("f" if "." in num or "e" in num.lower() else ".f")
        return num
    if _INT_LIT.match(v) and ctype.decl in ("int32", "uint32", "int64", "uint64", "int16", "uint16", "uint8", "int8"):
        return re.sub(r"[uUlL]+$", "", v)
    if m and ctype.decl in ("int32", "float", "double"):
        return m.group(1)
    if v.startswith('"') and ctype.decl == "FString":
        return f"TEXT({v})"
    if v.startswith('@"') and ctype.decl == "FString":
        return f"TEXT({v[1:]})"
    em = re.fullmatch(r"(\w+)\.(\w+)", v)
    if em and em.group(1) in project_types and project_types[em.group(1)].kind == "enum":
        return f"{project_types[em.group(1)].cpp_name}::{em.group(2)}"
    vm = re.fullmatch(r"new\s+Vector3\s*\(\s*([^,]+),\s*([^,]+),\s*([^,)]+)\)", v)
    if vm and ctype.decl == "FVector":
        x, y, z = (cpp_float(a) for a in vm.groups())
        if None not in (x, y, z):
            # Cambio de ejes Unity(x,y,z)->UE(z,x,y). Unidades sin convertir (revisar m->cm).
            return f"FVector({z}, {x}, {y})"
    vm = re.fullmatch(r"new\s+Vector2\s*\(\s*([^,]+),\s*([^,)]+)\)", v)
    if vm and ctype.decl == "FVector2D":
        x, y = (cpp_float(a) for a in vm.groups())
        if None not in (x, y):
            return f"FVector2D({x}, {y})"
    cm = re.fullmatch(r"new\s+Color\s*\(\s*([^,]+),\s*([^,]+),\s*([^,]+)(?:,\s*([^,)]+))?\)", v)
    if cm and ctype.decl == "FLinearColor":
        comps = [cpp_float(a) if a else "1.f" for a in cm.groups()]
        if None not in comps:
            return f"FLinearColor({', '.join(comps)})"  # type: ignore[arg-type]
    if v.startswith("new ") and ctype.decl.startswith(("TArray", "TMap", "TSet")) and v.endswith("()"):
        return None  # contenedor vacío: valor por defecto
    return None


def cpp_float(v: str) -> str | None:
    m = _FLOAT_LIT.match(v.strip())
    if not m:
        return None
    num = m.group(1)
    return num + ("f" if "." in num or "e" in num.lower() else ".f")
