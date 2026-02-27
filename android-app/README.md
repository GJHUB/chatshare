# GuDu Android App

Android WebView shell app for ChatShare site.

- App: `咕嘟` (`GuDu`)
- Package: `com.gudu.chat`
- URL: `http://140.143.185.247:8100`
- Min SDK: 24
- Target SDK: 34

## Features

- Full-screen WebView for ChatShare
- Splash screen with hotpot branding
- File upload via picker/camera
- Download support via `DownloadManager`
- Back key web history + double-tap exit
- Friendly network/server error page
- Cookie persistence for login state
- HTTP cleartext support for current server

## Build

Open `android-app/` in Android Studio (Giraffe+), sync Gradle, then build APK.

If CLI build is needed, generate wrapper from Android Studio first and run:

```bash
./gradlew assembleDebug
```
