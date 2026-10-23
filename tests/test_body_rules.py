"""Traducción por reglas de cuerpos de métodos C# -> C++ (unity2ue/convert/body_rules.py)."""
from unity2ue.convert.context import RESERVED_UE_NAMES
from unity2ue.convert.cpp_gen import CppGenerator, build_plans
from unity2ue.convert.csharp import parse_csharp
from unity2ue.naming import to_pascal


def _naming(name, kind):
    n = to_pascal(name)
    return n + "Component" if n in RESERVED_UE_NAMES else n


def _gen(files):
    plans, types = build_plans({p: parse_csharp(s) for p, s in files.items()}, _naming)
    gen = CppGenerator("MyGame", types)
    out = {p.unity_path: (p, *gen.generate(p)) for p in plans}
    return out, types, gen


def _one(src, name="Assets/Foo.cs"):
    out, _, gen = _gen({name: src})
    plan, h, c = out[name]
    return plan, h, c, gen


def test_rotator_fixture_update(sample_project):
    src = (sample_project / "Assets/Scripts/Rotator.cs").read_text()
    plan, h, c, _ = _one(src, "Assets/Scripts/Rotator.cs")
    assert plan.rule_translated == 1 and plan.rule_stub == 0
    assert "UNITY2UE_STATUS: TRANSLATED" in h
    assert "GetOwner()->GetRootComponent()->AddLocalRotation(" in c
    assert "FMath::DegreesToRadians(DegreesPerSecond * DeltaTime)" in c  # Time.deltaTime -> parámetro de Update


def test_transform_math_and_lists():
    plan, h, c, _ = _one("""
using UnityEngine;
using System.Collections.Generic;
public class Mover : MonoBehaviour {
    public float speed = 2f;
    public float groundY;
    public List<Transform> targets = new List<Transform>();
    void Update() {
        var pos = transform.position;
        pos.y = Mathf.MoveTowards(pos.y, groundY, speed * Time.deltaTime);
        transform.position = pos;
        foreach (var t in targets) {
            if ((t.position - pos).sqrMagnitude < 0.25f) { Debug.Log("cerca"); break; }
        }
        transform.position += Vector3.forward * speed * Time.deltaTime;
        int n = targets.Count;
        for (int i = 0; i < n; i++) { targets[i].position = Vector3.Lerp(pos, Vector3.zero, 0.5f); }
    }
}""")
    assert plan.rule_translated == 1 and plan.rule_stub == 0
    assert "auto pos = UUnityCompatLibrary::UnrealToUnityLocation(GetOwner()->GetRootComponent()->GetComponentLocation());" in c
    assert "pos.Y = UUnityCompatLibrary::MoveTowards(pos.Y, GroundY, Speed * DeltaTime);" in c
    assert "GetOwner()->GetRootComponent()->SetWorldLocation(UUnityCompatLibrary::UnityToUnrealLocation(pos));" in c
    assert "for (USceneComponent* t : Targets)" in c
    assert "(UUnityCompatLibrary::UnrealToUnityLocation(t->GetComponentLocation()) - pos).SizeSquared() < 0.25f" in c
    assert 'UNITY_LOG("cerca");' in c
    # += sobre una propiedad de Unity se expande con el getter
    assert "SetWorldLocation(UUnityCompatLibrary::UnityToUnrealLocation(" in c and "+ (FVector(0.f, 0.f, 1.f) * Speed * DeltaTime)" in c
    assert "int32 n = Targets.Num();" in c
    assert "for (int32 i = 0; i < n; i++)" in c
    assert "Targets[i]->SetWorldLocation(UUnityCompatLibrary::UnityToUnrealLocation(FMath::Lerp(pos, FVector::ZeroVector, 0.5f)));" in c


def test_events_properties_switch_and_prefs():
    out, types, gen = _gen({
        "Assets/GameEvents.cs": """
using System;
public static class GameEvents {
    public static event Action OnStart;
    public static event Action<int> OnScore;
    public static void Start() => OnStart?.Invoke();
    public static void Score(int value) => OnScore?.Invoke(value);
}""",
        "Assets/Hud.cs": """
using UnityEngine;
public class Hud : MonoBehaviour {
    public enum Mode { Idle, Running }
    private Mode _mode;
    private int _score;
    public int Score => _score;
    public bool IsRunning { get { return _mode == Mode.Running; } }
    void OnEnable() { GameEvents.OnStart += HandleStart; GameEvents.OnScore += HandleScore; }
    void OnDisable() { GameEvents.OnStart -= HandleStart; GameEvents.OnScore -= HandleScore; }
    private void HandleStart() { _mode = Mode.Running; PlayerPrefs.SetInt("runs", PlayerPrefs.GetInt("runs", 0) + 1); }
    private void HandleScore(int value) {
        _score += value;
        switch (_mode) {
            case Mode.Idle: break;
            case Mode.Running: Debug.Log($"Puntos: {_score} ({value})"); break;
        }
    }
}""",
    })
    plan, h, c = out["Assets/GameEvents.cs"]
    assert plan.rule_stub == 0 and plan.rule_translated == 2
    assert "static FUnityEvent OnStart;" in h and "static FUnityEvent_Int OnScore;" in h
    assert "OnStart.Broadcast();" in c and "OnScore.Broadcast(Value);" in c
    delegates = gen.delegates_header()
    assert "DECLARE_DYNAMIC_MULTICAST_DELEGATE_OneParam(FUnityEvent_Int, int32, Arg0);" in delegates
    assert '#include "Unity/UnityDelegates.h"' in h

    plan, h, c = out["Assets/Hud.cs"]
    assert plan.rule_stub == 0, plan.rule_reasons
    assert "UGameEvents::OnStart.AddDynamic(this, &UHud::HandleStart);" in c
    assert "UGameEvents::OnScore.RemoveDynamic(this, &UHud::HandleScore);" in c
    # los manejadores privados pasan a UFUNCTION para poder usar AddDynamic
    assert "UFUNCTION(BlueprintCallable, Category = \"Unity\")\n\tvoid HandleScore(int32 Value);" in h
    assert "UUnityCompatLibrary::PrefsSetInt(TEXT(\"runs\"), UUnityCompatLibrary::PrefsGetInt(TEXT(\"runs\"), 0) + 1);" in c
    assert "case EMode::Running:" in c and "switch (Mode)" in c
    assert 'UNITY_LOG("%s", *(FString::Printf(TEXT("Puntos: %d (%d)"), Score, Value)));' in c
    # getters de propiedades con lógica traducidos
    assert "int32 UHud::GetScore() const" in c and "\treturn Score;" in c
    assert "bool UHud::GetIsRunning() const" in c and "return Mode == EMode::Running;" in c


def test_instantiate_destroy_and_components():
    plan, h, c, _ = _one("""
using UnityEngine;
public class Spawner : MonoBehaviour {
    public Man manPrefab;
    public GameObject fxPrefab;
    public AudioClip clip;
    private Man _last;
    void Spawn() {
        _last = Instantiate(manPrefab, transform.position, Quaternion.identity);
        var fx = Instantiate(fxPrefab);
        fx.transform.SetParent(transform);
        fx.SetActive(false);
        AudioSource.PlayClipAtPoint(clip, transform.position);
        var man = GetComponent<Man>();
        if (man != null) Destroy(man.gameObject, 2f);
        Invoke("Spawn", Random.Range(1f, 3f));
    }
}
public class Man : MonoBehaviour { public int hp = 3; }
""")
    assert plan.rule_stub == 0, plan.rule_reasons
    assert ("Last = Instantiate(ManPrefab, UUnityCompatLibrary::UnityToUnrealLocation("
            "UUnityCompatLibrary::UnrealToUnityLocation(GetOwner()->GetRootComponent()->GetComponentLocation())), "
            "UUnityCompatLibrary::UnityToUnrealQuat(FQuat::Identity).Rotator())->FindComponentByClass<UMan>();") in c
    assert "auto fx = Instantiate(FxPrefab, FVector::ZeroVector, FRotator::ZeroRotator);" in c
    assert "fx->GetRootComponent()->AttachToComponent(GetOwner()->GetRootComponent(), FAttachmentTransformRules::KeepWorldTransform);" in c
    assert "UUnityCompatLibrary::SetActive(fx, false);" in c
    assert "UGameplayStatics::PlaySoundAtLocation(this, Clip," in c and '#include "Kismet/GameplayStatics.h"' in h
    assert "auto man = GetComponent<UMan>();" in c
    assert "DestroyActor(man->GetOwner(), 2.f);" in c
    assert "InvokeAfter(UUnityCompatLibrary::RandomRange(1.f, 3.f), [this]() { Spawn(); });" in c


def test_unsupported_methods_stay_as_todo_with_reason():
    plan, h, c, _ = _one("""
using UnityEngine;
using System.Linq;
using System.Collections;
public class Mixed : MonoBehaviour {
    public int[] values;
    void Ok() { Debug.Log("hola"); }
    int Sum() { return values.Sum(); }
    IEnumerator Wait() { yield return null; }
}""")
    assert plan.rule_translated == 1 and plan.rule_stub == 2
    assert {m for _, m, _ in plan.rule_reasons} == {"Sum", "Wait"}
    reasons = dict((m, why) for _, m, why in plan.rule_reasons)
    assert "LINQ" in reasons["Sum"]
    assert "UNITY2UE_STATUS: STUB" in h
    assert "// TODO(unity2ue): traducir el cuerpo original C# de Sum:" in c
    assert "Métodos traducidos por reglas: 1; pendientes (TODO): 2." in h
