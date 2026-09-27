from unity2ue.convert.csharp import mask_code, parse_csharp


def test_mask_keeps_positions_and_hides_braces():
    src = 'var s = "a { b"; // } comentario\n/* { */ int x;'
    masked = mask_code(src)
    assert len(masked) == len(src)
    assert "{" not in masked and "}" not in masked
    assert "int x;" in masked


def test_parse_sample(sample_project):
    src = (sample_project / "Assets/Scripts/PlayerController.cs").read_text()
    f = parse_csharp(src)
    names = {t.name: t for t in f.all_types()}
    assert set(names) >= {"MoveMode", "PlayerController", "Stats"}
    pc = names["PlayerController"]
    assert pc.bases == ["MonoBehaviour"] and pc.namespace == "Sample.Gameplay"
    fields = {fl.name: fl for fl in pc.fields}
    assert fields["moveSpeed"].serialized and fields["moveSpeed"].default == "5f"
    assert not fields["rb"].serialized
    assert not fields["PlayerCount"].serialized
    assert fields["Greeting"].default == '"Hola { mundo }"'
    methods = {m.name: m for m in pc.methods}
    assert {"Awake", "Update", "OnTriggerEnter", "Fire", "Blink", "Double"} <= set(methods)
    assert "rb.AddForce" in methods["Update"].body
    assert methods["Double"].expression_bodied
    assert names["MoveMode"].enum_values == ["Walk", "Run", "Fly"]
    props = {p.name: p for p in pc.properties}
    assert props["IsGrounded"].source.endswith("= true;")


def test_file_scoped_namespace_and_generics():
    f = parse_csharp(
        "namespace Game;\n"
        "public class Inventory : MonoBehaviour {\n"
        "  public Dictionary<string, List<int>> items = new();\n"
        "  public T Get<T>(int i) where T : class { return null; }\n"
        "}\n"
    )
    t = f.types[0]
    assert t.namespace == "Game"
    assert t.fields[0].type == "Dictionary<string, List<int>>"
    assert t.methods[0].name == "Get"
