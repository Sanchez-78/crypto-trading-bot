import requests
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

_cache_time = 0.0
_cached_events = []
CACHE_DURATION = 3600 * 4  # 4 hours

def get_high_impact_events():
    global _cache_time, _cached_events
    
    if time.time() - _cache_time < CACHE_DURATION and _cached_events:
        return _cached_events
        
    try:
        # Volno dostupné zrcadlo ForexFactory dat (FairEconomy)
        url = "https://nfs.faireconomy.media/ff_calendar_thisweek.xml"
        r = requests.get(url, timeout=10)
        
        if r.status_code != 200:
            return _cached_events
            
        root = ET.fromstring(r.text)
        
        events = []
        for event in root.findall("event"):
            impact = event.find("impact").text
            country = event.find("country").text
            
            if impact == "High" and country == "USD":
                date_str = event.find("date").text  # e.g. "11-05-2023"
                time_str = event.find("time").text  # e.g. "8:30am"
                
                # Ignorujme "All Day" nebo "Tentative" události pro přesný časový blok
                if "am" not in time_str and "pm" not in time_str:
                    continue
                    
                dt_str = f"{date_str} {time_str}"
                
                try:
                    # FF feed is Eastern Time (US/Eastern)
                    # simplified parsing: just convert to standard struct and guess offset
                    dt = datetime.strptime(dt_str, "%m-%d-%Y %I:%M%p")
                    # Přibližná konverze z EST/EDT do UTC (+4 nebo +5 hodin, hrubý odhad)
                    # Lepší je varovat prostě kolem dané hodiny obecně
                    utc_timestamp = dt.timestamp() + (4 * 3600)  
                    events.append(utc_timestamp)
                except Exception:
                    pass
                    
        _cached_events = events
        _cache_time = time.time()
        print(f"🌍 Macro Guard: Staženo {len(events)} úderových událostí z ekonomického kalendáře.")
        return events
        
    except Exception as e:
        print(f"⚠️ Macro Guard error: {e}")
        return _cached_events

def is_safe() -> bool:
    """
    Returns True if we are NOT within ±30 minutes of a high impact USD economic event.
    """
    events = get_high_impact_events()
    now = time.time()
    
    for ev_time in events:
        # Pokud je aktuální čas do 30 minut před nebo 30 minut po zprávě, vrať False
        if abs(now - ev_time) < 1800:
            return False
            
    return True

if __name__ == "__main__":
    print(f"Is market safe to trade now? {is_safe()}")
