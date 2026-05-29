# V5 Bot Android App with Firebase Integration

## Overview
Android application to monitor V5 Bot paper trading metrics with Firebase integration for data persistence and offline support.

## Features

### Real-Time Monitoring
- Live bot metrics (positions, trades, PnL)
- Paper trading learning metrics with timestamps
- Per-symbol performance breakdown
- Firebase quota monitoring
- Auto-refresh every 2-10 seconds

### Firebase Integration
- Offline data caching
- Historical metrics storage
- Real-time database synchronization
- Per-symbol performance tracking

### UI Components
- **Dashboard**: Current bot status and metrics
- **Learning History**: Complete trade history with timestamps
- **Per-Symbol Analysis**: Performance breakdown by trading pair
- **Quota Monitor**: Firebase quota usage visualization

## Project Structure

```
android_app/
├── build.gradle.kts              # Dependencies and build config
├── src/main/
│   ├── AndroidManifest.xml       # App permissions and activities
│   ├── java/com/cryptomaster/v5bot/
│   │   ├── MainActivity.kt        # Entry point
│   │   ├── V5BotApplication.kt   # Hilt app class
│   │   ├── data/
│   │   │   ├── api/
│   │   │   │   ├── V5BotApi.kt                # Retrofit API interface
│   │   │   │   └── RetrofitClient.kt         # Retrofit configuration
│   │   │   ├── models/
│   │   │   │   └── LearningMetrics.kt        # Data classes (Kotlin)
│   │   │   └── firebase/
│   │   │       └── FirebaseMetricsRepository.kt  # Firebase persistence
│   │   ├── ui/
│   │   │   ├── screens/
│   │   │   │   ├── MetricsScreen.kt          # Bot metrics dashboard
│   │   │   │   └── LearningMetricsScreen.kt  # Trade history & learning
│   │   │   ├── theme/
│   │   │   │   └── Theme.kt                  # Material Design theme
│   │   │   └── viewmodel/
│   │   │       └── MetricsViewModel.kt       # Data management
│   │   └── di/
│   │       └── RepositoryModule.kt           # Dependency injection
│   └── res/
│       ├── values/strings.xml
│       └── values/colors.xml
```

## Setup Instructions

### 1. Project Creation

```bash
# Create new Android project in Android Studio
File → New → New Project
- Template: Empty Activity (Compose)
- Name: CryptoMaster_V5Bot
- Package: com.cryptomaster.v5bot
- Min API: 24
- Target API: 34
```

### 2. Firebase Setup

#### Create Firebase Project
1. Go to [Firebase Console](https://console.firebase.google.com)
2. Create new project: "V5-Bot-Metrics"
3. Enable Google Analytics (optional)
4. Create web or Android app

#### Add Firebase to Android App
1. Download `google-services.json` from Firebase Console
2. Place in `android_app/` directory
3. In `build.gradle.kts` (project level):
```kotlin
plugins {
    id("com.google.gms.google-services") version "4.4.0" apply false
}
```
4. In `build.gradle.kts` (app level):
```kotlin
plugins {
    id("com.google.gms.google-services")
}
```

#### Firebase Realtime Database
1. Go to Realtime Database tab in Firebase Console
2. Create database in your region
3. Start in **test mode** (for development)
4. Security rules (for production):

```json
{
  "rules": {
    "metrics": {
      ".read": "auth != null",
      ".write": false
    },
    "learning": {
      ".read": "auth != null",
      ".write": "auth != null"
    }
  }
}
```

### 3. Configuration

#### Update Bot Server URL
In `RetrofitClient.kt`, change BASE_URL:
```kotlin
private const val BASE_URL = "http://192.168.1.100:5000/"
// Replace 192.168.1.100 with your bot server IP
```

For remote access (production):
```kotlin
private const val BASE_URL = "https://your-domain.com/api/"
```

#### Firebase Initialization
Add to `MainActivity.kt` onCreate:
```kotlin
// Firebase auto-initializes, but you can configure options:
val options = FirebaseOptions.Builder()
    .setProjectId("v5-bot-metrics")
    .setDatabaseUrl("https://v5-bot-metrics.firebaseio.com")
    .build()
FirebaseApp.initializeApp(this, options)
```

### 4. Dependencies Installation

All dependencies are in `build.gradle.kts`. Gradle will auto-download:
- Firebase Database SDK
- Retrofit & OkHttp
- Jetpack Compose
- Hilt dependency injection

### 5. Build & Run

```bash
# Build
./gradlew build

# Run on emulator/device
./gradlew installDebug
adb shell am start -n com.cryptomaster.v5bot/.MainActivity

# Or use Android Studio Run button
```

## Usage

### Tabs

#### Metrics Tab (Default)
Shows current bot status:
- Bot running/stopped status
- Feed connection status
- Open positions and notional value
- Current trading signals
- PnL and performance metrics
- Firebase quota usage

**Refresh Frequency**: Every 2 seconds (auto)

#### Learning Tab
Shows complete trading history:
- Overall statistics (total trades, win rate, PnL)
- Per-symbol performance breakdown
- Trade-by-trade history with:
  - Entry/exit timestamps
  - Prices and quantities
  - PnL and costs
  - Hold duration
  - Outcome (WIN/LOSS/FLAT)

**Refresh Frequency**: Every 10 seconds (auto)

### Features

#### Auto-Refresh
- Metrics: Every 2 seconds
- Learning history: Every 10 seconds
- Health check on startup

#### Manual Refresh
Tap the refresh button in app header to fetch latest data immediately.

#### Offline Support
Firebase caches data locally. When offline:
- Cached metrics remain visible
- New API calls fail gracefully
- Error message shows connection status

## Firebase Data Structure

### Location: `/metrics/snapshots/{timestamp}/`
```json
{
  "total_trades_closed": 9,
  "open_positions": 2,
  "total_net_pnl_usd": 45.75,
  "timestamp": "2026-05-29T12:39:00Z"
}
```

### Location: `/learning/latest/`
```json
{
  "total_trades_closed": 9,
  "total_wins": 6,
  "total_losses": 2,
  "win_rate": 0.67,
  "total_net_pnl_usd": 45.75,
  "total_fees_usd": 3.50,
  "timestamp": "2026-05-29T13:25:00Z",
  "trades_count": 9
}
```

### Location: `/learning/trades/{trade_id}/`
```json
{
  "symbol": "BTCUSDT",
  "entry_side": "BUY",
  "entry_price": 73258.55,
  "exit_price": 73350.25,
  "entry_timestamp": "2026-05-29T12:34:15Z",
  "exit_timestamp": "2026-05-29T12:45:30Z",
  "net_pnl_usd": 15.30,
  "outcome": "WIN"
}
```

## Architecture

### MVVM Pattern
- **ViewModel** (`MetricsViewModel`): Data management, auto-refresh
- **Repository** (`FirebaseMetricsRepository`): Firebase persistence
- **API Service** (`V5BotApi`): HTTP calls to bot server
- **UI** (Compose screens): Display and user interaction

### Data Flow
```
Bot Server
    ↓ (HTTP REST)
RetrofitClient (V5BotApi)
    ↓
MetricsViewModel (collects, manages state)
    ↓
FirebaseMetricsRepository (persists locally)
    ├─ Firebase Realtime Database (sync)
    └─ Local cache (offline)
    ↓
Compose UI (displays to user)
```

### Dependency Injection (Hilt)
- `RepositoryModule` provides singletons
- Auto-injects in ViewModels
- Thread-safe Firebase access

## API Endpoints Used

```
GET /metrics                      # Full metrics snapshot
GET /metrics/learning-history     # Complete learning history (timestamp + per-symbol + trades)
GET /health                       # Connection health check
```

See `ANDROID_API_EXAMPLES.md` for complete API specification.

## Troubleshooting

### Firebase Connection Issues
```
Error: "Cannot find Firebase configuration"
Solution: Ensure google-services.json is in android_app/ (not in src/)
```

### Bot Server Connection Issues
```
Error: "Failed to fetch metrics: Connect timeout"
Solution: 
1. Check bot server is running: curl http://192.168.1.100:5000/health
2. Update BASE_URL in RetrofitClient.kt to correct IP/domain
3. Ensure firewall allows port 5000
```

### Data Not Syncing to Firebase
```
Solution:
1. Check Firebase Realtime Database is enabled
2. Verify security rules allow writes
3. Check app has internet permission
4. Restart app
```

### Offline Mode Not Working
```
Solution:
1. Enable offline persistence in Firebase
2. Data must have been fetched at least once
3. Local cache expires after 30 days
```

## Development Workflow

### Adding New Metrics
1. Add fields to data models (`LearningMetrics.kt`)
2. Add to Retrofit interface (`V5BotApi.kt`)
3. Update ViewModel to fetch (`MetricsViewModel.kt`)
4. Add UI component (`*Screen.kt`)

### Changing API Endpoint
Edit `RetrofitClient.kt`:
```kotlin
private const val BASE_URL = "http://new-server:5000/"
```

### Customizing Theme
Edit `Theme.kt`:
```kotlin
private val DarkColorScheme = darkColorScheme(
    primary = Color(0xFF4CAF50),  // Green
    secondary = Color(0xFF2196F3),  // Blue
    // ...
)
```

## Production Checklist

- [ ] Firebase project created and configured
- [ ] Bot server endpoint updated in `RetrofitClient.kt`
- [ ] Firebase security rules configured
- [ ] Internet permission in `AndroidManifest.xml`
- [ ] App signing key generated
- [ ] Build signed APK: `./gradlew assembleRelease`
- [ ] Test on physical device (not just emulator)
- [ ] Firebase quota limits adjusted if needed
- [ ] Error handling for poor connectivity

## Performance Optimization

### Network
- Auto-refresh intervals (2s / 10s) prevent excessive API calls
- HTTP connection timeout: 30 seconds
- Gzip compression enabled by default

### Battery
- Run in background service for long-running monitoring
- Reduce refresh frequency when not in foreground
- Use WorkManager for periodic syncs

### Storage
- Firebase caches locally by default
- Trade history stored efficiently
- Old snapshots cleaned up after 30 days

## Testing

### Unit Tests
```kotlin
// Test ViewModel
@Test
fun testLearningHistoryFetch() {
    // Mock API response
    val mockHistory = LearningHistory(...)
    
    // Execute
    viewModel.fetchLearningHistory()
    
    // Assert
    assertEquals(mockHistory.totalTradesClosed, viewModel.learningHistory.value?.totalTradesClosed)
}
```

### Integration Tests
```kotlin
// Test Firebase sync
@Test
fun testFirebaseSync() {
    repository.saveLearningHistory(mockHistory)
    
    // Verify data in Firebase
    database.reference.child("learning/latest").get().addOnSuccessListener { snapshot ->
        assertEquals(mockHistory.totalNetPnlUsd, snapshot.value.toString())
    }
}
```

## Security Considerations

1. **API Communication**
   - Use HTTPS in production (change BASE_URL)
   - Enable SSL pinning for bot server

2. **Firebase Auth**
   - Enable authentication (currently test mode)
   - Use service accounts for backend writes

3. **Data Encryption**
   - Firebase auto-encrypts in transit
   - Enable at-rest encryption in production

4. **Sensitive Data**
   - Don't log API responses with PII
   - Secure sensitive configuration in BuildConfig

## Monitoring & Analytics

Firebase Analytics auto-tracks:
- App installs and launches
- Crashes (if enabled)
- Custom events (implement as needed)

Add custom event tracking:
```kotlin
FirebaseAnalytics.getInstance(context).logEvent("metrics_loaded") {
    param("timestamp", System.currentTimeMillis())
}
```

## Summary

Android app with:
- ✅ Real-time metrics monitoring via Retrofit
- ✅ Firebase integration for offline access
- ✅ Complete trade history with timestamps
- ✅ Per-symbol performance analysis
- ✅ Modern Compose UI
- ✅ Dependency injection (Hilt)
- ✅ MVVM architecture

Ready for production deployment with Firebase backend for data persistence and offline support.
