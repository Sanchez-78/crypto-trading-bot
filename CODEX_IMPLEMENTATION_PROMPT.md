# Codex Implementation Prompt - V5 Bot Android App with Firebase

## Task: Complete Android App Implementation

### Overview
Implement a complete Android application that monitors V5 Bot paper trading metrics in real-time with Firebase integration. The app displays learning metrics with timestamps, per-symbol breakdown, and trade history.

### Source Files & Structure

#### Existing V5 Bot Backend (Reference)
- Bot API Server: `src/v5_bot/paper/__main__.py` (runs on port 5000)
- Metrics API: `src/v5_bot/api/metrics_api.py` (provides `/metrics/learning-history` endpoint)
- Learning history includes: trade_id, symbol, entry/exit timestamps, prices, PnL, fees, outcome

#### New Android Project Files (Already Created - Copy These)
```
android_app/
├── build.gradle.kts
├── src/main/
│   ├── AndroidManifest.xml
│   └── java/com/cryptomaster/v5bot/
│       ├── MainActivity.kt
│       ├── V5BotApplication.kt
│       ├── data/
│       │   ├── api/
│       │   │   ├── V5BotApi.kt
│       │   │   └── RetrofitClient.kt
│       │   ├── models/
│       │   │   └── LearningMetrics.kt
│       │   └── firebase/
│       │       └── FirebaseMetricsRepository.kt
│       ├── ui/
│       │   ├── screens/
│       │   │   ├── MetricsScreen.kt
│       │   │   └── LearningMetricsScreen.kt
│       │   ├── theme/
│       │   │   └── Theme.kt
│       │   └── viewmodel/
│       │       └── MetricsViewModel.kt
│       └── di/
│           └── RepositoryModule.kt
```

### Implementation Requirements

#### 1. Project Setup
- Create new Android project in Android Studio
- Copy all files from `android_app/` directory
- Configure Firebase Console and download `google-services.json`
- Place `google-services.json` in `android_app/` (root level)

#### 2. Build Configuration
File: `android_app/build.gradle.kts`
- Add Firebase BOM (Bill of Materials) version 32.3.1
- Add dependencies:
  - Firebase Realtime Database KTX
  - Firebase Auth KTX
  - Firebase Analytics KTX
  - Retrofit2 (2.9.0)
  - OkHttp3 with logging interceptor (4.10.0)
  - Gson (2.10.1)
  - Jetpack Compose (1.5.0)
  - Material3 (1.1.0)
  - Hilt (2.47)
  - Coroutines (1.7.1)
- Apply plugins: com.android.application, kotlin-android, kotlin-kapt, com.google.gms.google-services
- Configure compileSDK=34, targetSDK=34, minSDK=24

#### 3. Data Models (Kotlin Data Classes)
File: `android_app/src/main/java/com/cryptomaster/v5bot/data/models/LearningMetrics.kt`

Create dataclasses:
1. **LearningHistory** with fields:
   - totalTradesClosed, totalWins, totalLosses, totalFlats: Int
   - winRate: Float?
   - totalNetPnlUsd, totalFeesUsd: Float
   - avgPnlPerTrade: Float?
   - perSymbolSummary: Map<String, PerSymbolLearning>
   - closedTrades: List<TradeRecord>
   - timestamp: String (ISO8601)

2. **PerSymbolLearning** with fields:
   - symbol: String (BTCUSDT, ETHUSDT, etc.)
   - tradesClosed, wins, losses, flats: Int
   - winRate: Float?
   - totalPnlUsd, avgPnlPerTrade, totalFeesUsd: Float
   - bestTradePnlUsd, worstTradePnlUsd: Float?

3. **TradeRecord** with fields:
   - tradeId, symbol, entrySide: String
   - entryPrice, exitPrice, qty, entryNotionalUsd: Float
   - entryTimestamp, exitTimestamp: String (ISO8601)
   - holdSeconds: Int
   - grossPnlUsd, grossPnlPct, netPnlUsd, netPnlPct: Float
   - totalCostsUsd, entryFeeUsd, exitFeeUsd, fundingCostUsd: Float
   - outcome: String (WIN, LOSS, FLAT)

4. **MetricsSnapshot** with 40+ fields (see ANDROID_API_EXAMPLES.md)

Use @SerializedName for JSON field mapping (snake_case ↔ camelCase)

#### 4. API Integration
File: `android_app/src/main/java/com/cryptomaster/v5bot/data/api/V5BotApi.kt`

Create Retrofit service interface:
```kotlin
interface V5BotApi {
    @GET("/metrics")
    suspend fun getMetrics(): MetricsSnapshot
    
    @GET("/health")
    suspend fun getHealth(): HealthResponse
    
    @GET("/metrics/learning-history")
    suspend fun getLearningHistory(): LearningHistory
    
    // Add other endpoints
}
```

File: `android_app/src/main/java/com/cryptomaster/v5bot/data/api/RetrofitClient.kt`

Create Retrofit singleton:
- BASE_URL: "http://192.168.1.100:5000/" (user will update IP)
- OkHttpClient with:
  - HttpLoggingInterceptor at BODY level
  - connectTimeout: 30 seconds
  - readTimeout: 30 seconds
  - writeTimeout: 30 seconds
- Retrofit with GsonConverterFactory
- Factory method: fun <T> createService(Class<T>): T
- Static method: fun getV5BotApi(): V5BotApi

#### 5. Firebase Integration
File: `android_app/src/main/java/com/cryptomaster/v5bot/data/firebase/FirebaseMetricsRepository.kt`

Create repository class:
- Get FirebaseDatabase reference
- Implement methods:
  - saveLearningHistory(learning: LearningHistory): Result<Unit>
  - getLearningHistoryStream(): Flow<Map<String, Any>?>
  - saveMetricsSnapshot(timestamp, metrics)
  - saveTrade(tradeId, tradeData)
  - getSymbolMetricsStream(symbol): Flow<Map<String, Any>?>
  - clearLocalCache(): Result<Unit>
- Use ValueEventListener for streams
- Return Flow<T> using callbackFlow
- Proper error logging and handling
- Use @Inject constructor

#### 6. ViewModel
File: `android_app/src/main/java/com/cryptomaster/v5bot/ui/viewmodel/MetricsViewModel.kt`

Create ViewModel with:
- MutableStateFlow for:
  - learningHistory: LearningHistory?
  - metrics: MetricsSnapshot?
  - isLoading: Boolean
  - error: String?
  - isConnected: Boolean
- Methods:
  - fetchLearningHistory() - Call API, save to Firebase
  - fetchMetrics() - Call API
  - checkHealth() - Verify connection
  - setServerUrl(url: String)
- Auto-refresh loops in init:
  - Metrics every 2000ms
  - Learning history every 10000ms
- Use viewModelScope for coroutines
- Mark with @HiltViewModel

#### 7. UI - Metrics Screen
File: `android_app/src/main/java/com/cryptomaster/v5bot/ui/screens/MetricsScreen.kt`

Create Composable function:
- Header with bot name and refresh button
- Status card showing:
  - Bot running/stopped
  - Feed connection status (color-coded)
  - Epoch ID
- Performance metrics card:
  - PnL (green if positive, red if negative)
  - Win rate percentage
  - Profit factor
- Trading activity card:
  - Entries attempted/successful/rejected
  - Trades closed
  - Uptime
- Current signals card:
  - Per-symbol signals (ACCEPTED/REJECTED)
- Firebase quota card:
  - Reads used/limit with percentage
  - Writes used/limit with percentage
  - Quota state (NORMAL/WARNING/EXHAUSTED) with colors
- Error card if error occurs
- Loading spinner if no data

#### 8. UI - Learning Metrics Screen
File: `android_app/src/main/java/com/cryptomaster/v5bot/ui/screens/LearningMetricsScreen.kt`

Create Composable with:
- Header with "Learning Metrics" title and refresh button
- Overall metrics card showing:
  - Total trades, wins, losses, flats
  - Win rate percentage
  - Total net PnL (color-coded)
  - Fees total
  - Average PnL per trade
  - Timestamp of collection
- Per-symbol section showing cards for each symbol with:
  - Symbol name
  - Trade count, wins, losses, flats
  - Win rate %
  - Total PnL (color-coded)
- Trade history section with LazyColumn showing:
  - Each trade in a card with:
    - Symbol (bold)
    - Entry side and price
    - Net PnL (green/red)
    - Hold seconds
    - Total fees
    - PnL%
    - Entry timestamp → Exit timestamp (formatted as HH:mm:ss)
    - Background color based on outcome (green for WIN, red for LOSS, gray for FLAT)

Helper functions:
- formatTimestamp(iso8601: String): String - Convert to HH:mm:ss
- MetricItem Composable for consistent formatting

#### 9. Theme
File: `android_app/src/main/java/com/cryptomaster/v5bot/ui/theme/Theme.kt`

Create Material Design 3 theme:
- Dark color scheme:
  - Primary: #4CAF50 (green)
  - Secondary: #2196F3 (blue)
  - Tertiary: #FF9800 (orange)
  - Background: #121212
  - Surface: #1E1E1E
  - Error: #F44336 (red)
- Light color scheme with same accent colors
- V5BotTheme Composable that applies MaterialTheme

#### 10. Manifest
File: `android_app/src/main/AndroidManifest.xml`

Configure:
- Package: com.cryptomaster.v5bot
- Permissions:
  - android.permission.INTERNET
  - android.permission.ACCESS_NETWORK_STATE
- Activity: MainActivity exported=true with MAIN/LAUNCHER intent filter
- Application name: V5BotApplication (for Hilt)

#### 11. Application Class
File: `android_app/src/main/java/com/cryptomaster/v5bot/V5BotApplication.kt`

Create:
- Class extending Application
- Annotate with @HiltAndroidApp

#### 12. Main Activity
File: `android_app/src/main/java/com/cryptomaster/v5bot/MainActivity.kt`

Create activity:
- Annotate with @AndroidEntryPoint
- Override onCreate():
  - setContent { V5BotTheme { ... } }
  - Create NavController with rememberNavController()
  - Create NavHost with startDestination="metrics"
  - composable("metrics") → MetricsScreen()
  - composable("learning") → LearningMetricsScreen()

#### 13. Dependency Injection Module
File: `android_app/src/main/java/com/cryptomaster/v5bot/di/RepositoryModule.kt`

Create Hilt module:
- Annotate @Module @InstallIn(SingletonComponent::class)
- Provide singleton V5BotApi:
  - @Provides @Singleton fun provideV5BotApi(): V5BotApi
  - Return RetrofitClient.getV5BotApi()
- Provide singleton FirebaseMetricsRepository:
  - @Provides @Singleton fun provideFirebaseMetricsRepository(): FirebaseMetricsRepository
  - Return new instance

### Key Technical Requirements

#### Kotlin & Android
- Use suspend functions for async API calls
- Use Flow for Firebase streams
- Use StateFlow in ViewModel
- Proper Composable state management with collectAsState()
- LazyColumn for scrolling lists
- Proper error handling with try-catch blocks
- Logging with android.util.Log

#### API Integration
- Retrofit with Gson converter
- OkHttp with logging interceptor
- Coroutines for async operations
- Proper timeout configuration

#### Firebase
- Realtime Database reads/writes
- ValueEventListener pattern
- callbackFlow for reactive streams
- Offline caching support
- Error handling and logging

#### UI/UX
- Material Design 3 components
- Proper spacing (16dp base)
- Color coding: green=success, red=error, gray=neutral
- Loading states with CircularProgressIndicator
- Error messages in Cards
- Responsive layouts using Row/Column with Arrangement

#### Architecture
- MVVM pattern (ViewModel manages state)
- Repository pattern (Firebase and API access)
- Dependency injection (Hilt)
- Clean separation of concerns

### Testing Points
1. Verify Retrofit deserializes JSON correctly
2. Confirm Firebase sync works with test data
3. Test offline mode - cache shows when no internet
4. Verify auto-refresh happens at correct intervals
5. Test error states and error messages display
6. Confirm color coding works (green/red/gray)
7. Verify timestamps format correctly

### Documentation to Include
1. How to update BASE_URL for different bot server
2. How to set up Firebase project
3. How to download google-services.json
4. Build and run instructions
5. Troubleshooting guide for common errors

### Deliverables
1. Complete android_app/ directory with all files
2. Fully functional Android app that:
   - Connects to bot server at http://192.168.1.100:5000
   - Fetches metrics every 2 seconds
   - Fetches learning history every 10 seconds
   - Displays metrics on MetricsScreen
   - Displays trade history on LearningMetricsScreen
   - Syncs data to Firebase Realtime Database
   - Works offline with cached data
   - Shows proper error states
3. Clear setup and deployment documentation

### Success Criteria
- App compiles without errors
- Can install on Android device/emulator
- Connects to bot server (if available)
- Displays metrics in real-time
- Shows complete trade history with timestamps
- Per-symbol breakdown is accurate
- Firebase sync works (with valid credentials)
- Offline mode functions correctly
- UI is responsive and properly formatted
- All colors and timestamps display correctly

---

## Start Implementation

Begin with:
1. Create Android project structure
2. Copy provided files to correct locations
3. Update gradle build configuration
4. Create data models with proper Gson annotations
5. Implement Retrofit API service
6. Set up Firebase repository
7. Build ViewModel with auto-refresh logic
8. Create UI screens with Compose
9. Configure theme and styling
10. Set up dependency injection
11. Create MainActivity and Application class

All code should follow Kotlin best practices, include proper error handling, logging, and follow Material Design 3 guidelines.
