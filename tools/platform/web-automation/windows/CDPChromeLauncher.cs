using System;
using System.Diagnostics;
using System.IO;
using System.Net;
using System.Threading;

internal static class CDPChromeLauncher
{
    // Slot identity is resolved per device instead of compiling in one host's
    // paths, so the same checkout works on any Windows machine. Environment
    // overrides let a second slot (for example 9223) reuse this launcher.
    private const int DefaultCdpPort = 9222;
    private const string DefaultProfileDirectory = "Default";

    private static readonly int CdpPort = ResolvePort();
    private static readonly string CdpUrl = "http://127.0.0.1:" + CdpPort;
    private static readonly string ProfileDir = ResolveProfileDir();
    private static readonly string ProfileDirectory = ResolveProfileDirectory();

    private static int ResolvePort()
    {
        string configured = Environment.GetEnvironmentVariable("CHROME_CDP_PORT");
        int parsed;
        if (!string.IsNullOrWhiteSpace(configured) && int.TryParse(configured, out parsed) && parsed > 0)
        {
            return parsed;
        }

        return DefaultCdpPort;
    }

    private static string ResolveProfileDir()
    {
        string configured = Environment.GetEnvironmentVariable("CHROME_CDP_USER_DATA_DIR");
        if (!string.IsNullOrWhiteSpace(configured))
        {
            return configured;
        }

        // Registered Windows slot roots: Chrome-CDP for 9222, Chrome-CDP-<port>
        // for any additional slot. Never the default Chrome user data root,
        // because Chrome 136+ blocks remote debugging there.
        string userHome = Environment.GetFolderPath(Environment.SpecialFolder.UserProfile);
        return Path.Combine(userHome, ".ai-control-center", "browser-profiles", "chrome", CdpPort, "UserData");
    }

    private static string ResolveProfileDirectory()
    {
        string configured = Environment.GetEnvironmentVariable("CHROME_CDP_PROFILE_DIRECTORY");
        return string.IsNullOrWhiteSpace(configured) ? DefaultProfileDirectory : configured;
    }

    private static bool Request(string method, string url)
    {
        try
        {
            var request = (HttpWebRequest)WebRequest.Create(url);
            request.Method = method;
            request.Timeout = 2500;
            using (var response = (HttpWebResponse)request.GetResponse())
            {
                return (int)response.StatusCode >= 200 && (int)response.StatusCode < 300;
            }
        }
        catch
        {
            return false;
        }
    }

    private static bool IsCdpReady()
    {
        return Request("GET", CdpUrl + "/json/version");
    }

    private static bool OpenTab(string target)
    {
        string endpoint = CdpUrl + "/json/new?" + Uri.EscapeDataString(target);
        return Request("PUT", endpoint) || Request("GET", endpoint);
    }

    private static string FindChrome()
    {
        string[] candidates =
        {
            @"C:\Program Files\Google\Chrome\Application\chrome.exe",
            @"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
            Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), @"Google\Chrome\Application\chrome.exe")
        };

        foreach (string candidate in candidates)
        {
            if (File.Exists(candidate))
            {
                return candidate;
            }
        }

        return null;
    }

    private static void LaunchChrome(string target)
    {
        Directory.CreateDirectory(ProfileDir);
        string chrome = FindChrome();
        if (chrome == null)
        {
            return;
        }

        string args =
            "--remote-debugging-address=127.0.0.1 " +
            "--remote-debugging-port=" + CdpPort + " " +
            "--user-data-dir=\"" + ProfileDir + "\" " +
            "--profile-directory=\"" + ProfileDirectory + "\" " +
            "--no-first-run --new-window \"" + target + "\"";

        Process.Start(new ProcessStartInfo
        {
            FileName = chrome,
            Arguments = args,
            UseShellExecute = false,
            CreateNoWindow = true
        });
    }

    /// Waits until the slot answers on its debugging port.
    ///
    /// The badge can only be attached over the DevTools protocol, so a cold
    /// start has to reach a listening endpoint first.
    private static void WaitForCdp()
    {
        for (int attempt = 0; attempt < 40; attempt++)
        {
            if (IsCdpReady())
            {
                return;
            }

            Thread.Sleep(500);
        }
    }

    /// Installs the port identity badge for the current browser process.
    ///
    /// Chrome removed `--load-extension` and an unpacked extension loaded over
    /// CDP is not written to the profile, so every new browser process needs the
    /// badge attached again. Failure never blocks the slot: the window stays
    /// usable and the next launch retries.
    private static void InstallBadgeExtension()
    {
        string aiccRoot = Environment.GetEnvironmentVariable("AICC_ROOT");
        if (string.IsNullOrWhiteSpace(aiccRoot))
        {
            string userHome = Environment.GetFolderPath(Environment.SpecialFolder.UserProfile);
            aiccRoot = Path.Combine(userHome, "dev", "projects", "tools", "ai-control-center");
        }

        string installer = Path.Combine(aiccRoot, "tools", "platform", "web-automation", "install-cdp-port-badge-extension.mjs");
        string extension = Path.Combine(aiccRoot, "tools", "platform", "web-automation", "extensions", "aicc-cdp-port-badge");
        if (!File.Exists(installer) || !File.Exists(Path.Combine(extension, "manifest.json")))
        {
            return;
        }

        try
        {
            var process = Process.Start(new ProcessStartInfo
            {
                FileName = "node",
                Arguments = "\"" + installer + "\""
                    + " --endpoint " + CdpUrl
                    + " --slot " + CdpPort
                    + " --extension \"" + extension + "\"",
                UseShellExecute = false,
                CreateNoWindow = true,
                RedirectStandardOutput = true,
                RedirectStandardError = true
            });

            if (process != null)
            {
                process.WaitForExit(30000);
            }
        }
        catch (Exception)
        {
            // The slot remains usable without its badge.
        }
    }

    private static int Main(string[] args)
    {
        string target = args.Length > 0 && !string.IsNullOrWhiteSpace(args[0])
            ? args[0]
            : "chrome://newtab/";

        if (IsCdpReady() && OpenTab(target))
        {
            InstallBadgeExtension();
            return 0;
        }

        LaunchChrome(target);
        WaitForCdp();
        InstallBadgeExtension();
        return 0;
    }
}
