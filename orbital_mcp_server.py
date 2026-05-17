import logging
import os
import re
from datetime import datetime, timezone
from typing import Literal, Optional

import requests
from dotenv import load_dotenv
from fastmcp import FastMCP
from pydantic import BaseModel, Field, field_validator
from skyfield.api import EarthSatellite, load, wgs84


load_dotenv()


class AppConfig(BaseModel):
    celestrak_url_template: str
    tle_request_timeout_seconds: float = Field(gt=0.0)
    skyfield_ephemeris_file: str
    mcp_server_name: str
    log_level: str
    log_format: str
    log_file_path: str
    mcp_transport: Literal["stdio", "http", "sse", "streamable-http"]
    mcp_host: str
    mcp_port: int = Field(ge=1, le=65535)
    mcp_path: str
    ephemeris_auto_download: bool
    ephemeris_download_url: str

    @staticmethod
    def _parse_bool(raw_value: str, key_name: str) -> bool:
        value = raw_value.strip().lower()
        if value in {"1", "true", "yes", "on"}:
            return True
        if value in {"0", "false", "no", "off"}:
            return False
        raise RuntimeError(
            f"Invalid boolean value for {key_name}: {raw_value}. Use true/false."
        )

    @classmethod
    def from_env(cls) -> "AppConfig":
        missing = [
            key
            for key in (
                "CELESTRAK_URL_TEMPLATE",
                "TLE_REQUEST_TIMEOUT_SECONDS",
                "SKYFIELD_EPHEMERIS_FILE",
                "MCP_SERVER_NAME",
                "LOG_LEVEL",
                "LOG_FORMAT",
                "LOG_FILE_PATH",
                "MCP_TRANSPORT",
                "MCP_HOST",
                "MCP_PORT",
                "MCP_PATH",
                "EPHEMERIS_AUTO_DOWNLOAD",
                "EPHEMERIS_DOWNLOAD_URL",
            )
            if not os.getenv(key)
        ]
        if missing:
            raise RuntimeError(
                "Missing required environment variables: " + ", ".join(sorted(missing))
            )

        return cls(
            celestrak_url_template=os.environ["CELESTRAK_URL_TEMPLATE"],
            tle_request_timeout_seconds=float(os.environ["TLE_REQUEST_TIMEOUT_SECONDS"]),
            skyfield_ephemeris_file=os.environ["SKYFIELD_EPHEMERIS_FILE"],
            mcp_server_name=os.environ["MCP_SERVER_NAME"],
            log_level=os.environ["LOG_LEVEL"],
            log_format=os.environ["LOG_FORMAT"],
            log_file_path=os.environ["LOG_FILE_PATH"],
            mcp_transport=os.environ["MCP_TRANSPORT"],
            mcp_host=os.environ["MCP_HOST"],
            mcp_port=int(os.environ["MCP_PORT"]),
            mcp_path=os.environ["MCP_PATH"],
            ephemeris_auto_download=cls._parse_bool(
                os.environ["EPHEMERIS_AUTO_DOWNLOAD"],
                "EPHEMERIS_AUTO_DOWNLOAD",
            ),
            ephemeris_download_url=os.environ["EPHEMERIS_DOWNLOAD_URL"],
        )


config = AppConfig.from_env()

log_dir = os.path.dirname(config.log_file_path)
if log_dir:
    os.makedirs(log_dir, exist_ok=True)

resolved_log_level = getattr(logging, config.log_level.upper(), logging.INFO)


# Configure detailed logging for runtime diagnostics.
logging.basicConfig(
    level=resolved_log_level,
    format=config.log_format,
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(config.log_file_path, encoding="utf-8"),
    ],
)
logger = logging.getLogger("orbital_predictor_mcp")
logger.info("Logging configured | level=%s | file=%s", config.log_level.upper(), config.log_file_path)
SAT_ID_PATTERN = re.compile(r"^[A-Za-z0-9]{1,9}$")


class SatelliteRequest(BaseModel):
    satellite_id: str = Field(
        ...,
        description="Satellite catalog identifier. Supports alphanumeric and up to 9 characters.",
        min_length=1,
        max_length=9,
    )
    latitude_deg: float = Field(..., ge=-90.0, le=90.0)
    longitude_deg: float = Field(..., ge=-180.0, le=180.0)
    elevation_m: float = Field(0.0, ge=-500.0, le=10000.0)
    minimum_visible_elevation_deg: float = Field(10.0, ge=0.0, le=90.0)

    @field_validator("satellite_id")
    @classmethod
    def validate_satellite_id(cls, value: str) -> str:
        sat_id = value.strip().upper()
        if not SAT_ID_PATTERN.match(sat_id):
            raise ValueError("satellite_id must be 1-9 alphanumeric characters")
        return sat_id


class SatelliteVisibilityResponse(BaseModel):
    satellite_id: str
    satellite_name: str
    requested_at_utc: str
    tle_epoch_utc: Optional[str]
    tle_age_hours: Optional[float]
    azimuth_deg: float
    elevation_deg: float
    distance_km: float
    is_sunlit: bool
    is_visible: bool
    visibility_reason: str


class TLEFetchError(RuntimeError):
    pass


class TLEParseError(RuntimeError):
    pass


def ensure_ephemeris_file() -> None:
    eph_path = config.skyfield_ephemeris_file
    if os.path.exists(eph_path):
        logger.info("Ephemeris file available | path=%s", eph_path)
        return

    if not config.ephemeris_auto_download:
        raise RuntimeError(
            "Ephemeris file not found and EPHEMERIS_AUTO_DOWNLOAD is disabled: "
            f"{eph_path}"
        )

    eph_dir = os.path.dirname(eph_path)
    if eph_dir:
        os.makedirs(eph_dir, exist_ok=True)

    logger.info(
        "Downloading ephemeris file | url=%s | target=%s",
        config.ephemeris_download_url,
        eph_path,
    )

    try:
        response = requests.get(
            config.ephemeris_download_url,
            timeout=config.tle_request_timeout_seconds,
            stream=True,
        )
        response.raise_for_status()
        with open(eph_path, "wb") as file_handle:
            for chunk in response.iter_content(chunk_size=1024 * 64):
                if chunk:
                    file_handle.write(chunk)
    except requests.RequestException as exc:
        logger.exception("Failed to download ephemeris file")
        raise RuntimeError(f"Failed to download ephemeris file: {exc}") from exc

    logger.info("Ephemeris download completed | path=%s", eph_path)


def fetch_tle(satellite_id: str, timeout_seconds: float) -> str:
    url = config.celestrak_url_template.format(id=satellite_id)
    logger.info("Step 1: Fetching TLE from CelesTrak | satellite_id=%s | url=%s", satellite_id, url)

    try:
        response = requests.get(url, timeout=timeout_seconds)
        response.raise_for_status()
    except requests.RequestException as exc:
        logger.exception("Failed to fetch TLE for satellite_id=%s", satellite_id)
        raise TLEFetchError(f"Failed to fetch TLE from CelesTrak: {exc}") from exc

    payload = response.text.strip()
    if not payload:
        logger.error("Empty TLE response for satellite_id=%s", satellite_id)
        raise TLEFetchError("Empty TLE response from CelesTrak")

    logger.info("Fetched TLE payload length=%d characters", len(payload))
    return payload


def _extract_id_from_tle_line(line1: str) -> Optional[str]:
    # Supports both traditional and alpha-numeric identifiers in line 1 tokenization.
    match = re.match(r"^1\s+([A-Za-z0-9]{1,10})", line1)
    if not match:
        return None

    token = match.group(1)
    if len(token) > 1 and token[-1].isalpha():
        token = token[:-1]

    token = token.strip().upper()
    if SAT_ID_PATTERN.match(token):
        return token
    return None


def parse_tle(payload: str, requested_satellite_id: str) -> tuple[str, str, str]:
    logger.info("Parsing TLE response for satellite_id=%s", requested_satellite_id)
    lines = [line.strip() for line in payload.splitlines() if line.strip()]

    if len(lines) < 2:
        logger.error("Insufficient TLE lines. lines=%s", lines)
        raise TLEParseError("TLE response does not contain enough lines")

    name = "UNKNOWN"
    line1 = ""
    line2 = ""

    for index in range(len(lines) - 1):
        current = lines[index]
        nxt = lines[index + 1]

        if current.startswith("1 ") and nxt.startswith("2 "):
            line1 = current
            line2 = nxt
            if index > 0 and not lines[index - 1].startswith(("1 ", "2 ")):
                name = lines[index - 1]
            break

    if not line1 or not line2:
        logger.error("Could not find valid TLE line pair in payload")
        raise TLEParseError("No valid TLE line pair found in response")

    parsed_id = _extract_id_from_tle_line(line1)
    if parsed_id is None:
        logger.warning("Could not extract satellite id from TLE line1=%s", line1)
    else:
        logger.info(
            "TLE parsed satellite id=%s | requested=%s",
            parsed_id,
            requested_satellite_id,
        )

    return name, line1, line2


def build_satellite(name: str, line1: str, line2: str, ts) -> EarthSatellite:
    logger.info("Building EarthSatellite object for name=%s", name)
    try:
        satellite = EarthSatellite(line1, line2, name=name, ts=ts)
    except Exception as exc:
        logger.exception("Skyfield failed to build EarthSatellite")
        raise TLEParseError(f"Unable to build satellite from TLE: {exc}") from exc
    return satellite


def compute_visibility(request: SatelliteRequest) -> SatelliteVisibilityResponse:
    logger.info("Starting orbital visibility computation | request=%s", request.model_dump())

    # Step 1: Fetch latest TLE data.
    payload = fetch_tle(
        request.satellite_id,
        timeout_seconds=int(config.tle_request_timeout_seconds),
    )
    name, line1, line2 = parse_tle(payload, request.satellite_id)

    # Step 2: Load timescale and ephemeris for Earth/Sun geometry.
    logger.info("Step 2: Loading timescale and ephemeris")
    try:
        ensure_ephemeris_file()
        ts = load.timescale()
        eph = load(config.skyfield_ephemeris_file)
    except Exception as exc:
        logger.exception("Failed to load Skyfield timescale or ephemeris")
        raise RuntimeError(f"Failed to initialize orbital resources: {exc}") from exc

    satellite = build_satellite(name, line1, line2, ts)

    # Step 3: Compute satellite position relative to observer.
    logger.info(
        "Step 3: Computing relative position | lat=%s lon=%s elev_m=%s",
        request.latitude_deg,
        request.longitude_deg,
        request.elevation_m,
    )
    observer = wgs84.latlon(
        latitude_degrees=request.latitude_deg,
        longitude_degrees=request.longitude_deg,
        elevation_m=request.elevation_m,
    )

    now = ts.now()
    difference = satellite - observer
    topocentric = difference.at(now)

    # Step 4: Calculate look angles and visibility logic.
    logger.info("Step 4: Calculating look angles and visibility criteria")
    alt, az, distance = topocentric.altaz()

    elevation_deg = float(alt.degrees)
    azimuth_deg = float(az.degrees)
    distance_km = float(distance.km)

    try:
        is_sunlit = bool(satellite.at(now).is_sunlit(eph))
    except Exception as exc:
        logger.exception("Failed to compute sunlit status")
        raise RuntimeError(f"Failed to compute sunlit status: {exc}") from exc

    meets_elevation = elevation_deg > request.minimum_visible_elevation_deg
    is_visible = bool(meets_elevation and is_sunlit)

    if is_visible:
        reason = "Visible: above elevation threshold and sunlit"
    elif not meets_elevation:
        reason = (
            f"Not visible: elevation {elevation_deg:.2f} is below "
            f"threshold {request.minimum_visible_elevation_deg:.2f}"
        )
    else:
        reason = "Not visible: satellite is not sunlit"

    tle_epoch_utc = None
    tle_age_hours = None
    try:
        epoch_dt = satellite.epoch.utc_datetime().replace(tzinfo=timezone.utc)
        tle_epoch_utc = epoch_dt.isoformat()
        tle_age_hours = (datetime.now(timezone.utc) - epoch_dt).total_seconds() / 3600.0
    except Exception:
        logger.warning("Could not compute TLE epoch age", exc_info=True)

    result = SatelliteVisibilityResponse(
        satellite_id=request.satellite_id,
        satellite_name=name,
        requested_at_utc=datetime.now(timezone.utc).isoformat(),
        tle_epoch_utc=tle_epoch_utc,
        tle_age_hours=tle_age_hours,
        azimuth_deg=azimuth_deg,
        elevation_deg=elevation_deg,
        distance_km=distance_km,
        is_sunlit=is_sunlit,
        is_visible=is_visible,
        visibility_reason=reason,
    )

    logger.info("Visibility computation completed | result=%s", result.model_dump())
    return result


mcp = FastMCP(config.mcp_server_name)


@mcp.tool(description="Predict satellite visibility from a ground location using real-time CelesTrak TLE.")
def predict_satellite_visibility(
    satellite_id: str,
    latitude_deg: float,
    longitude_deg: float,
    elevation_m: float = 0.0,
    minimum_visible_elevation_deg: float = 10.0,
) -> SatelliteVisibilityResponse:
    try:
        request = SatelliteRequest(
            satellite_id=satellite_id,
            latitude_deg=latitude_deg,
            longitude_deg=longitude_deg,
            elevation_m=elevation_m,
            minimum_visible_elevation_deg=minimum_visible_elevation_deg,
        )
        return compute_visibility(request)
    except (TLEFetchError, TLEParseError, RuntimeError, ValueError) as exc:
        logger.error("Handled visibility prediction error: %s", exc)
        raise
    except Exception as exc:
        logger.exception("Unhandled visibility prediction error")
        raise RuntimeError(f"Unexpected error during visibility prediction: {exc}") from exc


if __name__ == "__main__":
    ensure_ephemeris_file()
    logger.info("Starting Orbital Predictor & Visibility MCP server")
    if config.mcp_transport == "stdio":
        logger.info("MCP transport=stdio | no TCP port is used")
        mcp.run(transport=config.mcp_transport)
    else:
        logger.info(
            "MCP transport=%s | host=%s | port=%s | path=%s",
            config.mcp_transport,
            config.mcp_host,
            config.mcp_port,
            config.mcp_path,
        )
        mcp.run(
            transport=config.mcp_transport,
            host=config.mcp_host,
            port=config.mcp_port,
            path=config.mcp_path,
            log_level=config.log_level.lower(),
        )
