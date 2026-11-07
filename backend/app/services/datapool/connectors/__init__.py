from .environment import CalendarConnector, FxConnector, WeatherConnector
from .hazards import EonetConnector, UsgsConnector
from .news import GdeltToneConnector, GoogleNewsConnector, RegionalTrendsConnector, WikipediaConnector
from .publisher_rss import PublisherRssConnector
from .social import BlueskyConnector, MastodonConnector, RedditConnector, XConnector, YouTubeConnector
from .world_monitor import WorldMonitorConnector

ALL = [WeatherConnector(), GoogleNewsConnector(), GdeltToneConnector(), WikipediaConnector(), CalendarConnector(), FxConnector(),
       RegionalTrendsConnector(), MastodonConnector(), BlueskyConnector(), RedditConnector(), YouTubeConnector(), XConnector(), PublisherRssConnector(),
       UsgsConnector(), EonetConnector(), WorldMonitorConnector()]
REGISTRY = {c.spec.key: c for c in ALL}
