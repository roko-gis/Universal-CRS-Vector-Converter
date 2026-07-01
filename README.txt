# Universal CRS Vector Converter

A robust and intelligent coordinate reference system (CRS) conversion tool for QGIS.

Universal CRS Vector Converter automatically analyzes vector layers, detects their spatial context, and suggests the most appropriate target coordinate systems for accurate reprojection.

Designed with reliability, maintainability, and performance in mind.

---

## Features

### Intelligent CRS Recommendations

Unlike traditional reprojection tools that require users to manually search through thousands of EPSG codes, Universal CRS Vector Converter automatically suggests suitable coordinate systems based on:

- layer location
- layer center coordinates
- source CRS type
- geographic region
- country-specific projections
- UTM zone detection

---

### Automatic Geographic ↔ Projected Logic

The converter understands the difference between:

- Geographic coordinate systems (latitude / longitude)
- Projected coordinate systems (meters / feet)

When using **Auto Mode**, it automatically recommends:

- projected systems for geographic layers
- geographic systems for projected layers

This helps reduce common reprojection mistakes.

---

### Country-Aware CRS Detection

The converter includes regional logic for several countries:

- Bulgaria
- United Kingdom
- Germany
- France
- Italy
- Spain
- United States

When a layer falls inside a supported region, local national projections are prioritized.

Example:

| Country | Preferred CRS |
|----------|---------------|
| Bulgaria | EPSG:7801 |
| UK | EPSG:27700 |
| Germany | EPSG:25832 |
| France | EPSG:2154 |

---

### Automatic UTM Zone Calculation

The algorithm calculates the correct UTM zone directly from layer coordinates.

Examples:

- EPSG:32632
- EPSG:32633
- EPSG:32634
- EPSG:32735

No manual lookup required.

---

### Multiple Conversion Modes

#### Auto Mode
Recommended CRS based on source type.

#### Projected Mode
Shows only projected coordinate systems.

#### Geographic Mode
Shows only geographic coordinate systems.

#### Show All Mode
Displays all available recommendations.

---

### Custom EPSG Support

Users can manually enter:

```
32633
```

or

```
EPSG:32633
```

The converter validates the input automatically.

---

### Asynchronous Processing

Large layers are processed using **QgsTask**, keeping the QGIS interface responsive during conversion.

Benefits:

- no UI freezing
- cancellation support
- safe callback execution
- improved user experience

---

### Layer Safety

The plugin performs extensive validation:

- layer existence checks
- CRS validity checks
- empty extent protection
- null guards
- invalid output detection
- conversion cancellation handling

---

### Performance Optimizations

Several optimizations are included:

#### LRU caching

Used for:

- CRS objects
- dynamic CRS lists

#### Feature count cache

Reduces unnecessary provider calls.

#### Center coordinate cache

Avoids repeated coordinate transformations.

#### Refresh throttling

Prevents excessive UI updates.

---

### Maintainable Architecture

The codebase separates responsibilities into independent components:

#### CRSController

Business logic and layer management.

#### ConversionTask

Background reprojection processing.

#### Dialog Layer

User interface only.

#### Helper Functions

Reusable validation and utility functions.

This separation improves:

- readability
- maintainability
- testability

---

## Why Use Universal CRS Vector Converter?

Many reprojection workflows inside QGIS require:

1. opening the native reproject tool
2. searching manually for EPSG codes
3. understanding local projections
4. selecting the correct UTM zone

Universal CRS Vector Converter automates these steps and provides context-aware recommendations.

The goal is not to replace QGIS reprojection capabilities, but to make them easier, faster, and safer.

---

## Reliability

The project includes:

- defensive programming techniques
- centralized logging
- exception handling
- cache management
- safe UI callbacks
- invalid state protection

The codebase is optimized for maintainability and static analysis tools such as SonarCloud.

---

## Requirements

- QGIS 3.x
- Python 3
- PyQt5

The software is implemented as a Python Processing Tool script and runs inside the QGIS Processing Framework.
---

## Version

Current version:

```
1.0.0
```

---

## Future Improvements

Planned features:

- additional country-specific CRS databases
- user favorites
- recent CRS history
- batch conversion
- settings dialog
- localization support
- plugin packaging for QGIS Plugin Repository

---

