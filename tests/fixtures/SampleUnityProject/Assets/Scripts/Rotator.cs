using UnityEngine;

public class Rotator : MonoBehaviour
{
    [Range(0f, 360f)] public float degreesPerSecond = 45f;
    public Vector3 axis = new Vector3(0, 1, 0);

    void Update()
    {
        transform.Rotate(axis, degreesPerSecond * Time.deltaTime);
    }
}
