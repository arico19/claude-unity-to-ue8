"""Recursos integrados de Unity (mallas primitivas, material por defecto, shaders)."""

BUILTIN_EXTRA_GUID = "0000000000000000e000000000000000"  # mallas primitivas
BUILTIN_DEFAULT_GUID = "0000000000000000f000000000000000"  # material/shader por defecto

# fileID -> (ruta UE, escala adicional en ejes UE X,Y,Z para igualar tamaño Unity)
# Unity: cubo 1 m, esfera diámetro 1 m, cilindro 1 m x 2 m alto, plano 10x10 m, quad 1x1 m.
# UE BasicShapes: cubo 100 cm, esfera 100 cm, cilindro 100x100 cm, plano 100x100 cm.
BUILTIN_MESHES: dict[int, tuple[str, str, tuple[float, float, float]]] = {
    10202: ("Cube", "/Engine/BasicShapes/Cube.Cube", (1.0, 1.0, 1.0)),
    10207: ("Sphere", "/Engine/BasicShapes/Sphere.Sphere", (1.0, 1.0, 1.0)),
    10206: ("Cylinder", "/Engine/BasicShapes/Cylinder.Cylinder", (1.0, 1.0, 2.0)),
    # UE no trae cápsula en BasicShapes: aproximamos con un cilindro.
    10208: ("Capsule", "/Engine/BasicShapes/Cylinder.Cylinder", (1.0, 1.0, 2.0)),
    10209: ("Plane", "/Engine/BasicShapes/Plane.Plane", (10.0, 10.0, 1.0)),
    # El Quad de Unity mira hacia -Z (vertical); el Plane de UE es horizontal.
    10210: ("Quad", "/Engine/BasicShapes/Plane.Plane", (1.0, 1.0, 1.0)),
}

BUILTIN_DEFAULT_MATERIAL = "/Engine/BasicShapes/BasicShapeMaterial.BasicShapeMaterial"
BUILTIN_MATERIAL_FILE_IDS = {10303, 10302, 10306, 10754, 10757}  # Default-Material, Sprites-Default...

# Shaders conocidos por GUID -> familia (para elegir material maestro)
KNOWN_SHADER_GUIDS = {
    "933532a4fcc9baf4fa0491de14d08ed7": "urp_lit",
    "8d2bb70cbf9db8d4da26e15b26e74248": "urp_simple_lit",
    "650dd9526735d5b46b79224bc6e94025": "urp_unlit",
    "6e4ae4064600d784cac1e41a9e6f2e59": "hdrp_lit",
    "c4edd00ff2db5b24391a4fcb1762e459": "hdrp_unlit",
}
# Shaders integrados (guid BUILTIN_DEFAULT_GUID) por fileID
BUILTIN_SHADER_FILE_IDS = {
    46: "standard",
    45: "standard_specular",
    7: "legacy_diffuse",
    10753: "sprites_default",
    10770: "ui_default",
    10755: "unlit_texture",
    10750: "unlit_color",
    10751: "unlit_transparent",
    10752: "unlit_cutout",
}

# Scripts de paquetes habituales (uGUI / TextMeshPro) identificados por GUID.
KNOWN_PACKAGE_SCRIPTS = {
    "fe87c0e1cc204ed48ad3b37840f39efc": "UnityEngine.UI.Image",
    "5f7201a12d95ffc409449d95f23cf332": "UnityEngine.UI.Text",
    "4e29b1a8efbd4b44bb3f3716e73f07ff": "UnityEngine.UI.Button",
    "0cd44c1031e13a943bb63640046fad76": "UnityEngine.UI.CanvasScaler",
    "dc42784cf147c0c48a680349fa168899": "UnityEngine.UI.GraphicRaycaster",
    "76c392e42b5098c458856cdf6ecaaaa1": "UnityEngine.EventSystems.EventSystem",
    "4f231c4fb786f3946a6b90b886c48677": "UnityEngine.EventSystems.StandaloneInputModule",
    "f4688fdb7df04437aeb418b961361dc5": "TMPro.TextMeshProUGUI",
    "9541d86e2fd84c1d9990edf0852d74ab": "TMPro.TextMeshPro",  # texto 3D (no UI)
}
