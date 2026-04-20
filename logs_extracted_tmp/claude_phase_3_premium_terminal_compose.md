# Fáze 3 — Premium Terminal redesign + konkrétní Compose screeny

## Úkol
Navrhni a implementuj moderní Android UI ve stylu Premium Terminal.

## Povinná pravidla
- celé UI musí být česky
- každá důležitá položka musí mít stručný kontext
- UI musí být čitelné na mobilu
- neodstraň klíčové metriky
- pokud projekt používá Jetpack Compose, implementuj v Compose

## Povinná struktura appky
1. Přehled
2. Portfolio
3. Výkon
4. Strategie
5. Systém

## Povinný styl
- tmavé grafitové pozadí
- prémiové zaoblené karty
- vysoká čitelnost čísel
- omezená sémantická barevnost
- zelená pozitivní, červená negativní, jantarová warning, modrá aktivní

## Povinné Compose části
### Design systém
- AppColors
- AppTypography
- AppSpacing
- AppShapes
- TradingTheme
- formatovací utility

### Komponenty
- HeroStatusCard
- MetricCard
- CompactMetricCard
- MetricWithContextCard
- WarningBanner
- FreshnessBanner
- SectionHeader
- MiniTrendCard
- EquityChartCard
- PositionCard
- HealthStatusCard
- ExpandableMetricGroup
- EmptyStateCard
- ErrorStateCard
- LoadingCard
- TimeRangeSwitcher

### Screeny
- PrehledScreen
- PortfolioScreen
- VykonScreen
- StrategieScreen
- SystemScreen

### UI modely
- PrehledUiState
- PortfolioUiState
- VykonUiState
- StrategieUiState
- SystemUiState
- PositionUiModel
- MetricUiModel
- WarningUiModel
- HealthItemUiModel

## Povinný výstup
Vrať pouze:
1. Shrnutí redesignu
2. Novou strukturu appky
3. Design systém
4. Tabulku komponent:
| Komponenta | Účel | Kde se používá |
5. Tabulku screenů:
| Screen | Hlavní sekce | Důležité metriky |
6. UI modely a navigaci
7. Změněné/přidané soubory
8. Konkrétní Kotlin/Compose kód
9. Validaci:
- vše je česky
- každá důležitá položka má kontext
- žádná klíčová metrika nechybí
- UI je čitelné na mobilu

Buď stručný a implementační.
