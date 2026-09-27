using UnityEngine;

[CreateAssetMenu(menuName = "Game/Weapon")]
public class WeaponData : ScriptableObject
{
    public string displayName = "Pistol";
    public int damage = 10;
    public AudioClip fireSound;
}
