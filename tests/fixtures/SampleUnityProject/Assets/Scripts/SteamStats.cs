using Steamworks;
using UnityEngine;

// Logros, estadísticas, marcadores y presencia con Steamworks.NET (para probar `unity2ue steam init`).
public class SteamStats : MonoBehaviour
{
    public int gamesPlayed;

    void Start()
    {
        if (!SteamManager.Initialized) return;
        SteamFriends.SetRichPresence("steam_display", "#Status_InMenu");
        SteamLeaderboard_t dummy;
        SteamUserStats.FindOrCreateLeaderboard("HighScores", ELeaderboardSortMethod.k_ELeaderboardSortMethodDescending, ELeaderboardDisplayType.k_ELeaderboardDisplayTypeNumeric);
    }

    public void OnWin()
    {
        gamesPlayed++;
        SteamUserStats.SetStat("NumGames", gamesPlayed);
        SteamUserStats.SetStat("FeetTraveled", 12.5f);
        SteamUserStats.SetAchievement("ACH_WIN_ONE_GAME");
        SteamUserStats.StoreStats();
        SteamFriends.SetRichPresence("steam_display", "#Status_Victory");
    }
}
