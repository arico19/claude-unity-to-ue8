using System.Collections;
using System.Collections.Generic;
using UnityEngine;

namespace Sample.Gameplay
{
    public enum MoveMode { Walk, Run = 2, Fly }

    [RequireComponent(typeof(Rigidbody))]
    public class PlayerController : MonoBehaviour
    {
        [System.Serializable]
        public struct Stats
        {
            public int health;
            public float armor;
        }

        [Header("Movement")]
        [SerializeField] private float moveSpeed = 5f;
        public float jumpForce = 7.5f;
        public MoveMode mode = MoveMode.Run;
        public GameObject bulletPrefab;
        public Transform muzzle;
        public List<AudioClip> footsteps = new List<AudioClip>();
        public Stats stats;
        private Rigidbody rb;
        public static int PlayerCount;
        private const string Greeting = "Hola { mundo }"; // llaves en string

        public bool IsGrounded { get; private set; } = true;
        public float Speed => moveSpeed;

        void Awake()
        {
            rb = GetComponent<Rigidbody>();
        }

        void Update()
        {
            float h = Input.GetAxis("Horizontal");
            /* comentario con { llave */
            transform.Translate(new Vector3(h, 0, 0) * moveSpeed * Time.deltaTime);
            if (Input.GetButtonDown("Jump") && IsGrounded)
            {
                rb.AddForce(Vector3.up * jumpForce, ForceMode.Impulse);
            }
        }

        void OnTriggerEnter(Collider other)
        {
            if (other.CompareTag("Coin")) { Destroy(other.gameObject); }
        }

        public void Fire(float spread, int count = 1)
        {
            for (int i = 0; i < count; i++)
                Instantiate(bulletPrefab, muzzle.position, muzzle.rotation);
        }

        IEnumerator Blink()
        {
            yield return new WaitForSeconds(0.5f);
        }

        private int Double(int x) => x * 2;
    }
}
