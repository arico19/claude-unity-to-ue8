from unity2ue.convert.context import RESERVED_UE_NAMES
from unity2ue.convert.cpp_gen import CppGenerator, build_plans
from unity2ue.convert.csharp import parse_csharp
from unity2ue.convert.type_map import TypeMapper
from unity2ue.naming import to_pascal


def _naming(name, kind):
    n = to_pascal(name)
    return n + "Component" if n in RESERVED_UE_NAMES else n


def _gen(files):
    plans, types = build_plans({p: parse_csharp(s) for p, s in files.items()}, _naming)
    gen = CppGenerator("MyGame", types)
    return {p.unity_path: (p, *gen.generate(p)) for p in plans}, types


def test_component_generation(sample_project):
    src = (sample_project / "Assets/Scripts/PlayerController.cs").read_text()
    out, types = _gen({"Assets/Scripts/PlayerController.cs": src})
    plan, header, cpp = out["Assets/Scripts/PlayerController.cs"]
    assert types["PlayerController"].cpp_name == "UPlayerControllerComponent"  # evita APlayerController
    assert '#include "PlayerControllerComponent.generated.h"' in header
    assert "class MYGAME_API UPlayerControllerComponent : public UUnityBehaviour" in header
    assert "float MoveSpeed = 5.f;" in header
    assert "EMoveMode Mode = EMoveMode::Run;" in header
    assert "TSubclassOf<AActor> BulletPrefab;" in header
    assert "TArray<TObjectPtr<USoundBase>> Footsteps;" in header
    assert "virtual void Update(float DeltaTime) override;" in header
    assert "virtual void OnTriggerEnter(AActor* Other) override;" in header
    assert "void Fire(float Spread, int32 Count = 1);" in header
    assert "USTRUCT(BlueprintType)" in header and "struct FStats" in header
    assert "void UPlayerControllerComponent::Fire(float Spread, int32 Count)" in cpp
    assert "//     rb.AddForce(Vector3.up * jumpForce, ForceMode.Impulse);" in cpp
    assert "UNITY2UE_STATUS: STUB" in header
    assert plan.field_maps["PlayerController"]["moveSpeed"] == "MoveSpeed"


def test_reserved_names_and_inheritance():
    out, types = _gen({
        "Assets/Rotator.cs": "public class Rotator : MonoBehaviour { public float speed; void Update() {} }",
        "Assets/Enemy.cs": "public class Enemy : Unit { public override void Hit() {} }",
        "Assets/Unit.cs": "public class Unit : MonoBehaviour { public virtual void Hit() {} public int Owner; }",
    })
    assert types["Rotator"].cpp_name == "URotatorComponent"  # FRotator
    _, enemy_h, _ = out["Assets/Enemy.cs"]
    assert "class MYGAME_API UEnemy : public UUnit" in enemy_h
    assert '#include "Unity/Unit.h"' in enemy_h
    assert "virtual void Hit() override;" in enemy_h
    plan, unit_h, _ = out["Assets/Unit.cs"]
    assert "int32 UnityOwner = 0;" in unit_h  # 'Owner' choca con miembros de UActorComponent
    assert plan.field_maps["Unit"]["Owner"] == "UnityOwner"


def test_scriptable_object_and_editor():
    out, types = _gen({
        "Assets/Data/Weapon.cs": "public class Weapon : ScriptableObject { public int damage = 3; }",
        "Assets/Editor/Tool.cs": "public class Tool : EditorWindow {}",
    })
    assert types["Weapon"].kind == "data_asset"
    assert "public UPrimaryDataAsset" in out["Assets/Data/Weapon.cs"][1]
    assert out["Assets/Editor/Tool.cs"][0].kind == "editor"


def test_type_mapper():
    m = TypeMapper()
    assert m.map("List<Vector3>").decl == "TArray<FVector>"
    assert m.map("Dictionary<string, GameObject>").decl == "TMap<FString, TObjectPtr<AActor>>"
    assert m.map("float[]").decl == "TArray<float>"
    assert m.map("GameObject", "enemyPrefab").decl == "TSubclassOf<AActor>"
    assert not m.map("NavMeshPath").uproperty


def test_uht_rules_found_compiling_in_ue58():
    """Errores reales de UHT/MSVC al compilar un proyecto Unity real en UE 5.8."""
    base = """
using UnityEngine;
using UnityEngine.Events;
using System.Collections.Generic;
public class BaseUnit : MonoBehaviour {
    public void Initialize(float hitDelay) {}
    public virtual void Hit() {}
}"""
    child = """
using UnityEngine;
using System.Collections.Generic;
public class Boss : BaseUnit {
    [SerializeField] private float targetPos;
    public List<int> Items => _items;
    private List<int> _items;
    public void Initialize() {}
    public override void Hit() {}
    public void Refresh() {}
    public void Refresh(Vector3 p) {}
    public void SetTargetPos(float targetPos) {}
    public void Follow(Other other) {}
    public void Subscribe(UnityEvent listener) {}
}"""
    out, _ = _gen({"Assets/BaseUnit.cs": base, "Assets/Boss.cs": child, "Assets/Other.cs": "using UnityEngine; public class Other : MonoBehaviour {}"})
    _, header, cpp = out["Assets/Boss.cs"]
    ufunc = '\tUFUNCTION(BlueprintCallable, Category = "Unity")\n'
    # Método que oculta/sobrescribe uno del padre: sin UFUNCTION.
    assert ufunc + "\tvoid Initialize();" not in header and "\tvoid Initialize();" in header
    assert ufunc + "\tvirtual void Hit() override;" not in header
    # Sobrecargas: sólo la primera es UFUNCTION.
    assert header.count(ufunc + "\tvoid Refresh(") == 1
    # Parámetro que oculta una propiedad: se renombra.
    assert "void SetTargetPos(float InTargetPos);" in header
    # Tipos de parámetros declarados en el header.
    assert "class UOther;" in header or '#include "Other.h"' in header
    # Delegado como parámetro: no puede ser UFUNCTION.
    assert ufunc + "\tvoid Subscribe(" not in header
    # Getter de colección por valor (return {} de una referencia no compila).
    assert "TArray<int32> GetItems() const;" in header
    assert "TArray<int32> UBoss::GetItems() const" in cpp
