using System;
using System.Diagnostics;
using System.IO;
using System.Net;
using System.Runtime.InteropServices;
using System.Threading;

internal static class CDPWhaleLauncher
{
    private const string CdpUrl = "http://127.0.0.1:9335";
    private static readonly string ProfileDir = Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.UserProfile),
        ".ai-control-center", "browser-profiles", "whale", "9335", "UserData");
    private const string ProfileDirectory = "Profile 1";
    private const int CdpPort = 9335;
    private const string AppUserModelId = "NaverWhale.CDP";
    private const string RelaunchDisplayName = "CDP Whale";
    // Keep the launcher portable across AICC moves. The icon is shipped
    // beside the executable, and the relaunch command uses the actual running
    // executable rather than a compiled-in repository path.
    private static readonly string RelaunchIcon = Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "cdp_whale_cdp.ico");
    private static readonly string LauncherPath = Path.GetFullPath(Environment.GetCommandLineArgs()[0]);
    private const string WatchIconsArgument = "--watch-icons";
    private const int ImageIcon = 1;
    private const int LargeIcon = 1;
    private const int SmallIcon = 0;
    private const int GclpHicon = -14;
    private const int GclpHiconSm = -34;
    private const int LrLoadFromFile = 0x00000010;
    private const int WmSetIcon = 0x0080;

    private delegate bool EnumWindowsProc(IntPtr hWnd, IntPtr lParam);

    private static IntPtr smallIconHandle = IntPtr.Zero;
    private static IntPtr largeIconHandle = IntPtr.Zero;

    [DllImport("shell32.dll")]
    private static extern int SHGetPropertyStoreForWindow(IntPtr hwnd, ref Guid iid, out IPropertyStore propertyStore);

    [DllImport("shell32.dll", CharSet = CharSet.Unicode)]
    private static extern int SetCurrentProcessExplicitAppUserModelID(string appId);

    [DllImport("user32.dll")]
    private static extern bool EnumWindows(EnumWindowsProc enumFunc, IntPtr lParam);

    [DllImport("user32.dll")]
    private static extern bool IsWindowVisible(IntPtr hwnd);

    [DllImport("user32.dll")]
    private static extern uint GetWindowThreadProcessId(IntPtr hwnd, out uint processId);

    [DllImport("user32.dll", CharSet = CharSet.Unicode)]
    private static extern IntPtr LoadImage(
        IntPtr instance,
        string name,
        uint type,
        int desiredWidth,
        int desiredHeight,
        uint load);

    [DllImport("user32.dll")]
    private static extern IntPtr SendMessage(IntPtr hwnd, uint message, IntPtr wParam, IntPtr lParam);

    [DllImport("user32.dll", EntryPoint = "SetClassLongPtr")]
    private static extern IntPtr SetClassLongPtr64(IntPtr hwnd, int index, IntPtr newLong);

    [DllImport("user32.dll", EntryPoint = "SetClassLong")]
    private static extern int SetClassLong32(IntPtr hwnd, int index, int newLong);

    [DllImport("ole32.dll")]
    private static extern int PropVariantClear(ref PropVariant pvar);

    [ComImport]
    [Guid("886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99")]
    [InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    private interface IPropertyStore
    {
        int GetCount(out uint cProps);
        int GetAt(uint iProp, out PropertyKey pkey);
        int GetValue(ref PropertyKey key, out PropVariant pv);
        int SetValue(ref PropertyKey key, ref PropVariant pv);
        int Commit();
    }

    [StructLayout(LayoutKind.Sequential, Pack = 4)]
    private struct PropertyKey
    {
        public Guid fmtid;
        public uint pid;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct PropVariant
    {
        public ushort vt;
        public ushort wReserved1;
        public ushort wReserved2;
        public ushort wReserved3;
        public IntPtr p;
        public int p2;
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

    private static string NormalizeTarget(string target)
    {
        if (string.IsNullOrWhiteSpace(target))
        {
            return "whale://newtab/";
        }

        target = target.Trim();

        Uri uri;
        if (Uri.TryCreate(target, UriKind.Absolute, out uri) && !string.IsNullOrWhiteSpace(uri.Scheme))
        {
            return target;
        }

        try
        {
            if (File.Exists(target) || Directory.Exists(target) || Path.IsPathRooted(target))
            {
                return new Uri(Path.GetFullPath(target)).AbsoluteUri;
            }
        }
        catch
        {
        }

        return target;
    }

    private static PropertyKey AppModelKey(uint pid)
    {
        return new PropertyKey
        {
            fmtid = new Guid("9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3"),
            pid = pid
        };
    }

    private static PropVariant StringPropVariant(string value)
    {
        return new PropVariant
        {
            vt = 31,
            p = Marshal.StringToCoTaskMemUni(value)
        };
    }

    private static void SetStringProperty(IPropertyStore store, uint pid, string value)
    {
        PropertyKey key = AppModelKey(pid);
        PropVariant pv = StringPropVariant(value);

        try
        {
            store.SetValue(ref key, ref pv);
        }
        finally
        {
            PropVariantClear(ref pv);
        }
    }

    private static IntPtr SetClassIcon(IntPtr hwnd, int index, IntPtr icon)
    {
        if (IntPtr.Size == 8)
        {
            return SetClassLongPtr64(hwnd, index, icon);
        }

        return new IntPtr(SetClassLong32(hwnd, index, icon.ToInt32()));
    }

    private static void EnsureIconHandles()
    {
        if (smallIconHandle == IntPtr.Zero)
        {
            smallIconHandle = LoadImage(
                IntPtr.Zero,
                RelaunchIcon,
                ImageIcon,
                16,
                16,
                LrLoadFromFile);
        }

        if (largeIconHandle == IntPtr.Zero)
        {
            largeIconHandle = LoadImage(
                IntPtr.Zero,
                RelaunchIcon,
                ImageIcon,
                32,
                32,
                LrLoadFromFile);
        }
    }

    private static void PatchWindowIcon(IntPtr hwnd)
    {
        EnsureIconHandles();

        if (smallIconHandle != IntPtr.Zero)
        {
            SendMessage(hwnd, WmSetIcon, new IntPtr(SmallIcon), smallIconHandle);
            SetClassIcon(hwnd, GclpHiconSm, smallIconHandle);
        }

        if (largeIconHandle != IntPtr.Zero)
        {
            SendMessage(hwnd, WmSetIcon, new IntPtr(LargeIcon), largeIconHandle);
            SetClassIcon(hwnd, GclpHicon, largeIconHandle);
        }
    }

    private static bool IsCdpWhaleProcess(Process process)
    {
        try
        {
            string commandLine = GetCommandLine(process);
            return commandLine.IndexOf("--remote-debugging-port=" + CdpPort, StringComparison.OrdinalIgnoreCase) >= 0
                && commandLine.IndexOf(ProfileDir, StringComparison.OrdinalIgnoreCase) >= 0;
        }
        catch
        {
            return false;
        }
    }

    private static string GetCommandLine(Process process)
    {
        try
        {
            string path = @"\\.\root\cimv2:Win32_Process.Handle='" + process.Id + "'";
            using (var managementObject = new System.Management.ManagementObject(path))
            {
                return (managementObject["CommandLine"] as string) ?? string.Empty;
            }
        }
        catch
        {
            return string.Empty;
        }
    }

    private static bool TryPatchWindowHandle(IntPtr hwnd, bool patchIcon)
    {
        try
        {
            if (hwnd == IntPtr.Zero)
            {
                return false;
            }

            Guid propertyStoreGuid = new Guid("886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99");
            IPropertyStore store;
            int hr = SHGetPropertyStoreForWindow(hwnd, ref propertyStoreGuid, out store);
            if (hr != 0 || store == null)
            {
                return false;
            }

            SetStringProperty(store, 2, "\"" + LauncherPath + "\" whale://newtab/");
            SetStringProperty(store, 3, RelaunchIcon);
            SetStringProperty(store, 4, RelaunchDisplayName);
            SetStringProperty(store, 5, AppUserModelId);
            store.Commit();

            if (patchIcon)
            {
                PatchWindowIcon(hwnd);
            }

            return true;
        }
        catch
        {
            return false;
        }
    }

    private static bool TryPatchWindow(Process process, bool patchIcon)
    {
        bool patched = false;
        uint targetProcessId = (uint)process.Id;

        EnumWindows(delegate (IntPtr hwnd, IntPtr lParam)
        {
            uint windowProcessId;
            GetWindowThreadProcessId(hwnd, out windowProcessId);

            if (windowProcessId == targetProcessId && IsWindowVisible(hwnd))
            {
                patched = TryPatchWindowHandle(hwnd, patchIcon) || patched;
            }

            return true;
        }, IntPtr.Zero);

        process.Refresh();
        if (process.MainWindowHandle != IntPtr.Zero)
        {
            patched = TryPatchWindowHandle(process.MainWindowHandle, patchIcon) || patched;
        }

        return patched;
    }

    private static bool PatchCdpWindow(bool patchIcon)
    {
        bool patched = false;

        foreach (Process process in Process.GetProcessesByName("whale"))
        {
            using (process)
            {
                if (IsCdpWhaleProcess(process))
                {
                    patched = TryPatchWindow(process, patchIcon) || patched;
                }
            }
        }

        return patched;
    }

    private static void WaitAndPatchCdpWindow()
    {
        DateTime deadline = DateTime.UtcNow.AddSeconds(15);

        while (DateTime.UtcNow < deadline)
        {
            if (PatchCdpWindow(false))
            {
                return;
            }

            Thread.Sleep(500);
        }
    }

    private static string FindWhale()
    {
        string[] candidates =
        {
            @"C:\Program Files\Naver\Naver Whale\Application\whale.exe",
            @"C:\Program Files (x86)\Naver\Naver Whale\Application\whale.exe",
            Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), @"Naver\Naver Whale\Application\whale.exe")
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

    private static void LaunchWhale(string target)
    {
        Directory.CreateDirectory(ProfileDir);
        string whale = FindWhale();
        if (whale == null)
        {
            return;
        }

        string args =
            "--remote-debugging-address=127.0.0.1 " +
            "--remote-debugging-port=" + CdpPort + " " +
            "--app-user-model-id=\"" + AppUserModelId + "\" " +
            "--user-data-dir=\"" + ProfileDir + "\" " +
            "--profile-directory=\"" + ProfileDirectory + "\" " +
            "--no-first-run --new-window \"" + target + "\"";

        Process.Start(new ProcessStartInfo
        {
            FileName = whale,
            Arguments = args,
            UseShellExecute = false,
            CreateNoWindow = true
        });
    }

    private static void StartIconWatcher()
    {
        try
        {
            Process.Start(new ProcessStartInfo
            {
                FileName = LauncherPath,
                Arguments = WatchIconsArgument,
                UseShellExecute = false,
                CreateNoWindow = true
            });
        }
        catch
        {
        }
    }

    private static int RunIconWatcher()
    {
        using (var mutex = new Mutex(false, @"Local\CDPWhaleIconWatcher"))
        {
            if (!mutex.WaitOne(0))
            {
                return 0;
            }

            DateTime watcherStarted = DateTime.UtcNow;
            DateTime lastSeen = watcherStarted;

            while (true)
            {
                DateTime now = DateTime.UtcNow;

                if (PatchCdpWindow(true))
                {
                    lastSeen = now;
                }
                else if (now - lastSeen > TimeSpan.FromSeconds(30))
                {
                    return 0;
                }

                Thread.Sleep(now - watcherStarted < TimeSpan.FromSeconds(20) ? 1000 : 15000);
            }
        }
    }

    private static int Main(string[] args)
    {
        SetCurrentProcessExplicitAppUserModelID(AppUserModelId);

        if (args.Length > 0 && string.Equals(args[0], WatchIconsArgument, StringComparison.OrdinalIgnoreCase))
        {
            return RunIconWatcher();
        }

        string target = NormalizeTarget(args.Length > 0 ? args[0] : null);

        if (IsCdpReady() && OpenTab(target))
        {
            WaitAndPatchCdpWindow();
            StartIconWatcher();
            return 0;
        }

        LaunchWhale(target);
        WaitAndPatchCdpWindow();
        StartIconWatcher();
        return 0;
    }
}
