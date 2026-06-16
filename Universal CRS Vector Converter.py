"""
Universal CRS Vector Converter 
Version 1.0.0 
"""

import processing
from qgis.core import (
    QgsProject, QgsCoordinateReferenceSystem, QgsVectorLayer,
    QgsWkbTypes, QgsMessageLog, Qgis, QgsTask, QgsApplication,
    QgsProcessingContext, QgsProcessingFeedback, QgsCoordinateTransform
)
from qgis.utils import iface
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QComboBox,
    QPushButton, QRadioButton, QGroupBox,
    QMessageBox, QCheckBox, QLineEdit, QProgressBar
)
from PyQt5.QtCore import QSettings, QTimer
from collections import OrderedDict
import traceback
from functools import lru_cache


# ============================================================================
# CONSTANTS
# ============================================================================

class CRS_IDS:
    WGS84 = "EPSG:4326"
    ETRS89 = "EPSG:4258"
    LAEA = "EPSG:3035"

WGS84_AUTH = CRS_IDS.WGS84
ETRS89_AUTH = CRS_IDS.ETRS89
LAEA_EUROPE_AUTH = CRS_IDS.LAEA

PROC_REPROJECT = "native:reprojectlayer"
PROC_INPUT = "INPUT"
PROC_TARGET = "TARGET_CRS"
PROC_OUTPUT = "OUTPUT"
TEMP_OUTPUT = "TEMPORARY_OUTPUT"

MIN_LONGITUDE = -180
MAX_LONGITUDE = 180
MIN_LATITUDE = -90
MAX_LATITUDE = 90

MODE_AUTO = "auto"
MODE_PROJECTED = "projected"
MODE_GEOGRAPHIC = "geographic"
MODE_ALL = "all"

FEATURE_CACHE_MAX = 50

STYLE_SMALL = "color: #666; font-size: 10px;"
STYLE_INFO = "color: #4CAF50; font-style: italic; font-size: 10px;"
STYLE_WARNING = "color: #ff9800; font-size: 10px;"
STYLE_BOLD = "font-weight: bold; padding: 5px;"

MSG_GEO_TO_PROJ = "⚠ Geographic → Projected (distortion possible)"
MSG_PROJ_TO_GEO = "Projected → Geographic (area/length will change)"
MSG_SAME_TYPE = "Same CRS type conversion"
MSG_NO_LAYER = "No valid vector layer selected"
MSG_DETECTING = "Detecting..."

COUNTRY_BBOXES = {
    "BULGARIA": (22.0, 41.0, 28.0, 44.5),
    "UK": (-8.0, 49.0, 2.0, 61.0),
    "GERMANY": (5.0, 47.0, 15.0, 55.0),
    "FRANCE": (-5.0, 42.0, 8.0, 51.0),
    "ITALY": (6.5, 35.5, 18.5, 47.0),
    "SPAIN": (-9.5, 36.0, 3.5, 43.8),
}

COUNTRY_CRS = {
    "BULGARIA": "EPSG:7801",
    "UK": "EPSG:27700",
    "USA_EAST": "EPSG:26918",
    "USA_WEST": "EPSG:26910",
    "GERMANY": "EPSG:25832",
    "FRANCE": "EPSG:2154",
    "ITALY": "EPSG:32632",
    "SPAIN": "EPSG:25830",
}


# ============================================================================
# UI HELPERS
# ============================================================================

def show_warning(parent, title, text):
    """Centralized warning dialog."""
    QMessageBox.warning(parent, title, text)

def show_info(parent, title, text):
    """Centralized info dialog."""
    QMessageBox.information(parent, title, text)

def show_error(parent, title, text):
    """Centralized error dialog."""
    QMessageBox.critical(parent, title, text)


# ============================================================================
# LOGGING
# ============================================================================

def log(level, msg):
    """Safe logging wrapper."""
    try:
        QgsMessageLog.logMessage(msg, "CRS Converter", level)
    except RuntimeError as e:
        print(f"LOG: {msg} - {e}")


# ============================================================================
# CRS ENGINE - PURE FUNCTIONS WITH LRU CACHE
# ============================================================================

def safe_crs_obj(epsg):
    """Get safe CRS object or None."""
    crs = get_crs(epsg)
    return crs if crs and crs.isValid() else None


@lru_cache(maxsize=512)
def get_crs(epsg):
    """Safe CRS creation with caching."""
    try:
        code = int(str(epsg).replace("EPSG:", ""))
        crs = QgsCoordinateReferenceSystem(f"EPSG:{code}")
        if crs.isValid():
            return crs
        return None
    except (ValueError, TypeError) as e:
        log(Qgis.Warning, f"get_crs failed: {e}")
        return None


def parse_epsg(text):
    """QGIS-native EPSG parsing."""
    if not text or not isinstance(text, str):
        return None
    try:
        text = text.strip()
        if not text.startswith("EPSG:"):
            text = f"EPSG:{text}"
        crs = QgsCoordinateReferenceSystem(text)
        if crs.isValid():
            return crs.authid()
        return None
    except ValueError as e:
        log(Qgis.Warning, f"parse_epsg failed: {e}")
        return None


def is_geographic_crs(crs):
    """Check if CRS is geographic."""
    return bool(crs and crs.isValid() and crs.isGeographic())


def calculate_utm_zone(lon):
    """Calculate UTM zone from longitude."""
    zone = int((lon + 180) / 6) + 1
    return max(1, min(zone, 60))


def get_utm_epsg(lon, lat):
    """Get UTM EPSG code for coordinates."""
    zone = calculate_utm_zone(lon)
    return f"EPSG:{32600 + zone}" if lat >= 0 else f"EPSG:{32700 + zone}"


def get_country_crs(lat, lon):
    """Get country-specific CRS based on bounding box."""
    if 35 < lat < 70 and -10 < lon < 40:
        for country, (min_lon, min_lat, max_lon, max_lat) in COUNTRY_BBOXES.items():
            if min_lon <= lon <= max_lon and min_lat <= lat <= max_lat:
                return COUNTRY_CRS.get(country)
    elif 24 < lat < 50 and -125 < lon < -65:
        return COUNTRY_CRS["USA_WEST"] if lon < -100 else COUNTRY_CRS["USA_EAST"]
    return None


def get_country_name_from_crs(crs_epsg):
    """Get country name from CRS EPSG code."""
    for name, epsg in COUNTRY_CRS.items():
        if epsg == crs_epsg:
            return name
    return None


@lru_cache(maxsize=256)
def get_dynamic_crs_list_cached(lon, lat, source_is_geographic, mode, project_crs):
    """Cached CRS list generation with project salt."""
    utm = get_utm_epsg(lon, lat)
    country_crs = get_country_crs(lat, lon)
    
    if mode == MODE_AUTO:
        if source_is_geographic:
            candidates = [utm, LAEA_EUROPE_AUTH]
            if country_crs:
                candidates.insert(0, country_crs)
        else:
            candidates = [WGS84_AUTH, ETRS89_AUTH]
    elif mode == MODE_PROJECTED:
        candidates = [utm, LAEA_EUROPE_AUTH]
        if country_crs:
            candidates.insert(0, country_crs)
    elif mode == MODE_GEOGRAPHIC:
        candidates = [WGS84_AUTH, ETRS89_AUTH]
    else:
        candidates = [utm, WGS84_AUTH, ETRS89_AUTH, LAEA_EUROPE_AUTH]
        if country_crs and country_crs not in candidates:
            candidates.insert(1, country_crs)
    
    valid = []
    for c in candidates:
        if get_crs(c) is not None:
            valid.append(c)
    return valid


def get_dynamic_crs_list(lon, lat, source_is_geographic, mode):
    """Wrapper for cached version with current project CRS."""
    project_crs = QgsProject.instance().crs().authid()
    return get_dynamic_crs_list_cached(lon, lat, source_is_geographic, mode, project_crs)


# ============================================================================
# VALIDATION HELPERS
# ============================================================================

def is_valid_layer(layer):
    """Central layer validation with full guards."""
    if layer is None:
        return False
    if not isinstance(layer, QgsVectorLayer):
        return False
    if not layer.isValid():
        return False
    crs = layer.crs()
    if crs is None:
        return False
    return crs.isValid()


def safe_layer_authid(layer):
    """Safe access to layer CRS authid."""
    if is_valid_layer(layer):
        return layer.crs().authid()
    return None


def get_layer_center_wgs84(layer, project):
    """Calculate layer center in WGS84."""
    try:
        if not is_valid_layer(layer):
            return None, None
        
        extent = layer.extent()
        if extent.isNull() or extent.isEmpty():
            return None, None
        
        cx = (extent.xMinimum() + extent.xMaximum()) / 2.0
        cy = (extent.yMinimum() + extent.yMaximum()) / 2.0
        
        crs = layer.crs()
        if crs.authid() != WGS84_AUTH:
            wgs84 = safe_crs_obj(WGS84_AUTH)
            if wgs84 is not None:
                transform = QgsCoordinateTransform(crs, wgs84, project)
                pt = transform.transform(cx, cy)
                return pt.x(), pt.y()
        return cx, cy
    except RuntimeError as e:
        log(Qgis.Warning, f"Center error: {e}")
        return None, None


# ============================================================================
# CONVERSION TASK
# ============================================================================

class ConversionTask(QgsTask):
    """Async conversion task with safe callbacks."""
    
    def __init__(self, layer_source, target_crs, source_auth, layer_name):
        super().__init__(f"Reproject {layer_name}", QgsTask.CanCancel)
        self.layer_source = layer_source
        self.target_crs = target_crs
        self.source_auth = source_auth
        self.layer_name = layer_name
        self.result_layer = None
        self.error = None
        self._callback = None
    
    def set_callback(self, callback):
        """Set completion callback."""
        self._callback = callback
    
    def run(self):
        try:
            if self.isCanceled():
                self.error = "Cancelled by user"
                return False
            
            self.setProgress(10)
            
            context = QgsProcessingContext()
            context.setProject(QgsProject.instance())
            context.setTransformContext(QgsProject.instance().transformContext())
            
            feedback = QgsProcessingFeedback()
            
            params = {
                PROC_INPUT: self.layer_source,
                PROC_TARGET: self.target_crs,
                PROC_OUTPUT: TEMP_OUTPUT
            }
            
            result = processing.run(
                PROC_REPROJECT,
                params,
                context=context,
                feedback=feedback
            )
            
            self.setProgress(90)
            
            if self.isCanceled():
                self.error = "Cancelled by user"
                return False
            
            output = result.get('OUTPUT')
            if not output:
                self.error = "Processing returned no output"
                return False
            
            if isinstance(output, str):
                new_layer = QgsVectorLayer(output, self.layer_name, "ogr")
            else:
                new_layer = output
            
            if new_layer is None or not new_layer.isValid():
                self.error = "Output layer is invalid"
                return False
            
            new_layer.setName(f"{self.layer_name} [{self.target_crs}]")
            self.result_layer = new_layer
            return True
            
        except RuntimeError as e:
            self.error = f"Error: {str(e)}"
            log(Qgis.Critical, f"Conversion failed: {traceback.format_exc()}")
            return False
    
    def finished(self, result):
        self.setProgress(100)
        if not self._callback:
            return
        
        QTimer.singleShot(0, lambda: self._callback(
            self.result_layer is not None,
            self.result_layer,
            self.error
        ))


# ============================================================================
# CRS CONTROLLER
# ============================================================================

class CRSController:
    """Business logic separated from UI."""
    
    def __init__(self):
        self.project = QgsProject.instance()
        self.layer = None
        self.center_lon = None
        self.center_lat = None
        self._feature_cache = OrderedDict()
        self._center_cache = None
        self._refreshing = False
        self._source_auth = None
        self._feature_count = None
    
    def set_refreshing(self, value):
        """Set refreshing state."""
        self._refreshing = value
    
    def is_refreshing(self):
        """Get refreshing state."""
        return self._refreshing
    
    def _has_valid_layer(self):
        return is_valid_layer(self.layer)
    
    def refresh_layer(self):
        """Refresh layer reference."""
        if iface is None:
            return None
        
        try:
            new_layer = iface.activeLayer()
        except RuntimeError as e:
            log(Qgis.Critical, f"Error accessing active layer: {e}")
            new_layer = None
        
        if new_layer and self.layer and self.layer.id() == new_layer.id():
            return self.layer
        
        self.layer = new_layer
        if self.layer:
            self.center_lon = None
            self.center_lat = None
            self._center_cache = None
            self._source_auth = safe_layer_authid(self.layer)
            self._feature_count = self._get_feature_count()
        
        return self.layer
    
    def refresh_center(self):
        """Refresh layer center coordinates."""
        if not self._has_valid_layer():
            self.center_lon = None
            self.center_lat = None
            return
        
        if self._center_cache and self._center_cache[0] == self.layer.id():
            self.center_lon, self.center_lat = self._center_cache[1], self._center_cache[2]
            return
        
        coords = get_layer_center_wgs84(self.layer, self.project)
        if coords and coords[0] is not None and coords[1] is not None:
            self.center_lon, self.center_lat = coords
            self._center_cache = (self.layer.id(), self.center_lon, self.center_lat)
        else:
            self.center_lon = None
            self.center_lat = None
    
    def _get_feature_count(self):
        """LRU cached feature count."""
        if not self._has_valid_layer():
            return None
        
        layer_id = self.layer.id()
        
        if layer_id in self._feature_cache:
            self._feature_cache.move_to_end(layer_id)
            return self._feature_cache[layer_id]
        
        try:
            fc = self.layer.dataProvider().featureCount()
            if fc < 0:
                fc = self.layer.featureCount()
            
            if fc >= 0:
                self._feature_cache[layer_id] = fc
                while len(self._feature_cache) > FEATURE_CACHE_MAX:
                    self._feature_cache.popitem(last=False)
                return fc
        except RuntimeError as e:
            log(Qgis.Warning, f"Feature count failed: {e}")
            return None
        
        return None
    
    def get_layer_info(self):
        """Get formatted layer information."""
        if not self._has_valid_layer():
            return MSG_NO_LAYER
        
        geom_type = QgsWkbTypes.geometryDisplayString(self.layer.geometryType())
        fc_str = f"{self._feature_count:,}" if self._feature_count is not None else "?"
        crs = self.layer.crs()
        crs_type = "Geographic" if crs and crs.isValid() and crs.isGeographic() else "Projected"
        
        info = f"LAYER: {self.layer.name()} ({geom_type}, {fc_str} features)\n"
        info += f"   Source CRS: {self._source_auth} [{crs_type}]"
        
        if self._source_auth and "USER:" in self._source_auth:
            info += "\n⚠ Unknown CRS detected"
        
        if self._feature_count == 0:
            info += "\n   EMPTY - 0 features"
        
        return info
    
    def get_region_info(self):
        """Get formatted region information."""
        if self.center_lon is None or self.center_lat is None:
            return "Could not detect region center"
        
        utm = get_utm_epsg(self.center_lon, self.center_lat)
        country_crs = get_country_crs(self.center_lat, self.center_lon)
        country_name = get_country_name_from_crs(country_crs) if country_crs else None
        country_text = f", Country: {country_name}" if country_name else ""
        
        return f"Center: {self.center_lon:.2f}, {self.center_lat:.2f} -> UTM: {utm}{country_text}"
    
    def build_crs_items(self, crs_list):
        """Build list of CRS items for UI."""
        items = []
        for i, epsg in enumerate(crs_list):
            crs = safe_crs_obj(epsg)
            if crs is None:
                continue
            
            crs_type = "Geographic" if crs.isGeographic() else "Projected"
            prefix = ">> " if i == 0 else "    "
            desc = crs.description()
            
            items.append({
                'text': f"{prefix}{epsg} - {desc} [{crs_type}]",
                'data': epsg
            })
        return items
    
    def get_crs_list_for_mode(self, mode):
        """Get CRS list based on current mode and center."""
        if self.center_lon is None or self.center_lat is None:
            return []
        
        source_is_geographic = False
        if self._has_valid_layer():
            crs = self.layer.crs()
            source_is_geographic = crs and crs.isValid() and crs.isGeographic()
        
        return get_dynamic_crs_list(self.center_lon, self.center_lat, source_is_geographic, mode)
    
    def has_valid_layer(self):
        return self._has_valid_layer()
    
    def get_source_auth(self):
        return self._source_auth
    
    def get_feature_count(self):
        return self._feature_count
    
    def get_layer(self):
        return self.layer


# ============================================================================
# MAIN DIALOG - REFACTORED
# ============================================================================

class CRSConverterDialog(QDialog):
    """Main dialog - UI presentation layer."""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("CRS Converter v1.9.4")
        self.setMinimumWidth(650)
        
        self.controller = CRSController()
        self.is_running = False
        self.current_task = None
        self._alive = True
        self._active_target_crs = None
        self._epsg_warning_shown = False
        
        self.settings = QSettings("CRSConverter", "CRSConverter")
        self.last_crs = self.settings.value("last_crs", "")
        self.last_mode = self.settings.value("last_mode", MODE_AUTO)
        
        self._refresh_timer = QTimer()
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.timeout.connect(self._refresh)
        
        self._build_ui()
        
        if self.last_mode == MODE_AUTO:
            self.auto_radio.setChecked(True)
        elif self.last_mode == MODE_PROJECTED:
            self.projected_radio.setChecked(True)
        elif self.last_mode == MODE_GEOGRAPHIC:
            self.geographic_radio.setChecked(True)
        else:
            self.all_radio.setChecked(True)
        
        self._schedule_refresh()
    
    def _build_ui(self):
        """Build all UI components - simplified structure."""
        layout = QVBoxLayout()
        
        self._build_header(layout)
        self._build_last_used(layout)
        self._build_mode_group(layout)
        self._build_region_info(layout)
        self._build_transform_info(layout)
        self._build_crs_selector(layout)
        self._build_custom_crs(layout)
        self._build_options(layout)
        self._build_progress(layout)
        self._build_status(layout)
        self._build_buttons(layout)
        
        self.setLayout(layout)
    
    def _build_header(self, layout):
        """Build info label."""
        self.info_label = QLabel(MSG_NO_LAYER)
        self.info_label.setStyleSheet(STYLE_BOLD)
        layout.addWidget(self.info_label)
    
    def _build_last_used(self, layout):
        """Build last used CRS label."""
        if self.last_crs:
            last_label = QLabel(f"Last used: {self.last_crs}")
            last_label.setStyleSheet(STYLE_SMALL)
            layout.addWidget(last_label)
    
    def _build_mode_group(self, layout):
        """Build conversion mode radio buttons."""
        mode_group = QGroupBox("Conversion Mode")
        mode_layout = QVBoxLayout()
        
        self.auto_radio = QRadioButton("Auto (recommended)")
        self.projected_radio = QRadioButton("To Projected (meters/feet)")
        self.geographic_radio = QRadioButton("To Geographic (lat/lon degrees)")
        self.all_radio = QRadioButton("Show All")
        
        for r in [self.auto_radio, self.projected_radio, self.geographic_radio, self.all_radio]:
            mode_layout.addWidget(r)
            r.toggled.connect(self._on_mode_changed)
        
        self.mode_info = QLabel("")
        self.mode_info.setStyleSheet(STYLE_INFO)
        mode_layout.addWidget(self.mode_info)
        mode_group.setLayout(mode_layout)
        layout.addWidget(mode_group)
    
    def _build_region_info(self, layout):
        """Build region detection label."""
        self.region_label = QLabel(MSG_DETECTING)
        self.region_label.setStyleSheet(STYLE_SMALL)
        layout.addWidget(self.region_label)
    
    def _build_transform_info(self, layout):
        """Build transform type info label."""
        self.transform_info = QLabel("")
        self.transform_info.setStyleSheet(STYLE_WARNING)
        layout.addWidget(self.transform_info)
    
    def _build_crs_selector(self, layout):
        """Build target CRS combo box."""
        layout.addWidget(QLabel("Target CRS:"))
        self.crs_combo = QComboBox()
        self.crs_combo.setMinimumHeight(32)
        self.crs_combo.activated.connect(self._on_combo_changed)
        layout.addWidget(self.crs_combo)
    
    def _build_custom_crs(self, layout):
        """Build custom EPSG input."""
        custom_layout = QHBoxLayout()
        custom_layout.addWidget(QLabel("Custom EPSG:"))
        self.custom_input = QLineEdit()
        self.custom_input.setPlaceholderText("e.g., 32633")
        self.custom_input.textChanged.connect(self._update_convert_button_state)
        self.custom_input.textChanged.connect(self._on_custom_changed)
        custom_layout.addWidget(self.custom_input)
        layout.addLayout(custom_layout)
    
    def _build_options(self, layout):
        """Build options checkboxes."""
        options_layout = QHBoxLayout()
        self.add_to_map_cb = QCheckBox("Add converted layer to map")
        self.add_to_map_cb.setChecked(True)
        options_layout.addWidget(self.add_to_map_cb)
        
        self.warn_same_crs_cb = QCheckBox("Warn when source = target")
        self.warn_same_crs_cb.setChecked(True)
        options_layout.addWidget(self.warn_same_crs_cb)
        
        layout.addLayout(options_layout)
    
    def _build_progress(self, layout):
        """Build progress bar."""
        self.progress = QProgressBar()
        self.progress.setVisible(False)
        layout.addWidget(self.progress)
    
    def _build_status(self, layout):
        """Build status label."""
        self.status_label = QLabel("")
        self.status_label.setStyleSheet(STYLE_SMALL)
        self.status_label.setVisible(False)
        layout.addWidget(self.status_label)
    
    def _build_buttons(self, layout):
        """Build action buttons."""
        btn_layout = QHBoxLayout()
        
        self.convert_btn = QPushButton("Convert")
        self.convert_btn.setStyleSheet("background: #4CAF50; color: white; padding: 8px; font-weight: bold;")
        self.convert_btn.clicked.connect(self._convert)
        btn_layout.addWidget(self.convert_btn)
        
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setStyleSheet("background: #f44336; color: white; padding: 8px;")
        self.cancel_btn.clicked.connect(self._cancel_conversion)
        self.cancel_btn.setVisible(False)
        btn_layout.addWidget(self.cancel_btn)
        
        refresh_btn = QPushButton("Refresh")
        refresh_btn.clicked.connect(self._schedule_refresh)
        btn_layout.addWidget(refresh_btn)
        
        btn_layout.addStretch()
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.close)
        btn_layout.addWidget(close_btn)
        
        layout.addLayout(btn_layout)
    
    def _schedule_refresh(self):
        self._refresh_timer.stop()
        self._refresh_timer.start(150)
    
    def _refresh(self):
        if self.controller.is_refreshing() or self.is_running:
            return
        
        self.controller.set_refreshing(True)
        try:
            self.controller.refresh_layer()
            
            if not self.controller.has_valid_layer():
                self.info_label.setText(MSG_NO_LAYER)
                self.convert_btn.setEnabled(False)
                return
            
            self.controller.refresh_center()
            
            info = self.controller.get_layer_info()
            self.info_label.setText(info)
            
            region_info = self.controller.get_region_info()
            self.region_label.setText(region_info)
            
            self._update_mode_info()
            self._update_list()
        finally:
            self.controller.set_refreshing(False)
    
    def _update_mode_info(self):
        if self.auto_radio.isChecked():
            if self.controller.has_valid_layer():
                crs = self.controller.layer.crs()
                if crs and crs.isValid() and crs.isGeographic():
                    self.mode_info.setText("Geographic source: Suggesting Projected CRS")
                else:
                    self.mode_info.setText("Projected source: Suggesting Geographic CRS")
            else:
                self.mode_info.setText("Auto: Suggests appropriate CRS")
        elif self.projected_radio.isChecked():
            self.mode_info.setText("Showing only Projected CRS")
        elif self.geographic_radio.isChecked():
            self.mode_info.setText("Showing only Geographic CRS")
        else:
            self.mode_info.setText("Showing all available CRS options")
        
        auth = self.controller.get_source_auth()
        if auth:
            self.mode_info.setText(f"{self.mode_info.text()} | Source: {auth}")
    
    def _get_current_mode(self):
        if self.auto_radio.isChecked():
            return MODE_AUTO
        elif self.projected_radio.isChecked():
            return MODE_PROJECTED
        elif self.geographic_radio.isChecked():
            return MODE_GEOGRAPHIC
        return MODE_ALL
    
    def _update_list(self):
        self.crs_combo.blockSignals(True)
        try:
            self.crs_combo.clear()
            
            if self.controller.center_lon is None or self.controller.center_lat is None:
                self.crs_combo.addItem("No location data available", None)
                return
            
            mode = self._get_current_mode()
            crs_list = self.controller.get_crs_list_for_mode(mode)
            items = self.controller.build_crs_items(crs_list)
            
            for item in items:
                self.crs_combo.addItem(item['text'], item['data'])
            
            if self.crs_combo.count() == 0:
                self.crs_combo.addItem("No suitable CRS found", None)
            
            if self.last_crs:
                idx = self.crs_combo.findData(self.last_crs)
                if idx != -1:
                    self.crs_combo.setCurrentIndex(idx)
                elif self.crs_combo.count() > 0:
                    self.crs_combo.setCurrentIndex(0)
            elif self.crs_combo.count() > 0:
                self.crs_combo.setCurrentIndex(0)
            
            self._update_transform_info()
        except RuntimeError as e:
            self.crs_combo.addItem(f"Error: {e}", None)
            log(Qgis.Critical, f"Update list error: {e}")
        finally:
            self.crs_combo.blockSignals(False)
            self._update_convert_button_state()
    
    def _update_transform_info(self):
        if not self.controller.has_valid_layer():
            self.transform_info.setText("")
            return
        
        target_crs = self._get_target_crs()
        if not target_crs:
            self.transform_info.setText("")
            return
        
        crs = self.controller.layer.crs()
        source_is_geo = crs and crs.isValid() and crs.isGeographic()
        target_crs_obj = safe_crs_obj(target_crs)
        target_is_geo = target_crs_obj and target_crs_obj.isGeographic() if target_crs_obj else False
        
        if source_is_geo and not target_is_geo:
            self.transform_info.setText(MSG_GEO_TO_PROJ)
        elif not source_is_geo and target_is_geo:
            self.transform_info.setText(MSG_PROJ_TO_GEO)
        else:
            self.transform_info.setText(MSG_SAME_TYPE)
    
    def _on_mode_changed(self):
        mode = self._get_current_mode()
        self.settings.setValue("last_mode", mode)
        self._update_mode_info()
        self._update_list()
    
    def _on_combo_changed(self):
        if self.crs_combo.currentIndex() >= 0 and self.crs_combo.currentData():
            self.custom_input.setText("")
        self._update_transform_info()
        self._update_convert_button_state()
    
    def _on_custom_changed(self):
        self.crs_combo.blockSignals(True)
        self.crs_combo.setCurrentIndex(-1)
        self.crs_combo.blockSignals(False)
        self._update_transform_info()
        self._update_convert_button_state()
    
    def can_convert(self):
        if self.is_running or not self.controller.has_valid_layer():
            return False
        target = self._get_target_crs()
        if not target:
            return False
        return safe_crs_obj(target) is not None
    
    def _update_convert_button_state(self):
        can = self.can_convert()
        self.convert_btn.setEnabled(can)
        
        if not can and self.controller.has_valid_layer():
            self.status_label.setText("Select valid CRS to enable conversion")
        else:
            self.status_label.setText("")
    
    def _get_target_crs(self):
        custom = self.custom_input.text()
        if custom and custom.strip():
            epsg = parse_epsg(custom)
            if epsg:
                self._epsg_warning_shown = False
                return epsg
            if not self._epsg_warning_shown:
                show_warning(self, "Invalid EPSG", f"'{custom}' is not a valid EPSG code.")
                self._epsg_warning_shown = True
            return None
        
        self._epsg_warning_shown = False
        
        if self.crs_combo.count() > 0:
            data = self.crs_combo.currentData()
            if data and isinstance(data, str) and data.startswith("EPSG:"):
                return data
        return None
    
    def _update_recent_crs(self, crs):
        self.settings.setValue("last_crs", crs)
        self.last_crs = crs
    
    def _cancel_conversion(self):
        if self.current_task and self.is_running:
            self.current_task.cancel()
            self.cancel_btn.setEnabled(False)
    
    def _set_controls_enabled(self, enabled):
        self.convert_btn.setEnabled(enabled and self.can_convert())
        self.crs_combo.setEnabled(enabled)
        self.custom_input.setEnabled(enabled)
        self.auto_radio.setEnabled(enabled)
        self.projected_radio.setEnabled(enabled)
        self.geographic_radio.setEnabled(enabled)
        self.all_radio.setEnabled(enabled)
    
    def _validate_conversion(self):
        """Validate if conversion can proceed."""
        if not self.can_convert():
            return False
        
        layer = self.controller.get_layer()
        if layer is None or not layer.isValid():
            show_warning(self, "Error", "Layer is no longer valid.")
            return False
        
        target_crs = self._get_target_crs()
        if not target_crs:
            return False
        
        source_auth = self.controller.get_source_auth()
        
        if source_auth == target_crs:
            if self.warn_same_crs_cb.isChecked():
                show_info(self, "Same CRS", f"Source and target are both {source_auth}")
            return False
        
        return True
    
    def _prepare_conversion_ui(self):
        """Prepare UI for conversion process."""
        self._set_controls_enabled(False)
        self.progress.setVisible(True)
        self.progress.setRange(0, 0)
        self.status_label.setVisible(True)
        self.status_label.setText("Reprojecting layer...")
        self.cancel_btn.setVisible(True)
        self.cancel_btn.setEnabled(True)
        self.convert_btn.setText("Converting...")
        self.is_running = True
    
    def _create_task(self, layer, target_crs):
        """Create conversion task."""
        task = ConversionTask(
            layer.source(),
            target_crs,
            self.controller.get_source_auth(),
            layer.name()
        )
        task.set_callback(self._on_conversion_finished)
        return task
    
    def _convert(self):
        """Main conversion method - simplified."""
        if not self._validate_conversion():
            return
        
        layer = self.controller.get_layer()
        target_crs = self._get_target_crs()
        self._active_target_crs = target_crs
        
        self._prepare_conversion_ui()
        
        self.current_task = self._create_task(layer, target_crs)
        QgsApplication.taskManager().addTask(self.current_task)
    
    def _on_conversion_finished(self, result, new_layer, error):
        if not getattr(self, "_alive", False):
            return
        
        self.is_running = False
        self._set_controls_enabled(True)
        self.progress.setVisible(False)
        self.status_label.setVisible(False)
        self.cancel_btn.setVisible(False)
        self.convert_btn.setText("Convert")
        
        if error:
            show_error(self, "Failed", f"Error: {error}")
            self.current_task = None
            self._schedule_refresh()
            return
        
        if result and new_layer:
            if self.add_to_map_cb.isChecked():
                QgsProject.instance().addMapLayer(new_layer)
            
            if self._active_target_crs:
                self._update_recent_crs(self._active_target_crs)
            
            show_info(self, "Success!", 
                f"Conversion completed!\n\n"
                f"From: {self.controller.get_source_auth()}\n"
                f"To: {self._active_target_crs}")
        
        self._active_target_crs = None
        self.current_task = None
        self._schedule_refresh()
    
    def closeEvent(self, event):
        if self.is_running:
            show_info(self, "Wait", "Conversion running. Please wait.")
            event.ignore()
        else:
            self._alive = False
            event.accept()


# ============================================================================
# RUN
# ============================================================================

def run():
    """Entry point."""
    if iface is None:
        print("CRS Converter: No QGIS interface")
        return
    
    layer = iface.activeLayer()
    if layer is None:
        show_warning(None, "No Layer", "Please select a vector layer first.")
        return
    
    if not isinstance(layer, QgsVectorLayer):
        show_warning(None, "Wrong Type", "Please select a vector layer.")
        return
    
    dlg = CRSConverterDialog(iface.mainWindow())
    dlg.exec_()


run()