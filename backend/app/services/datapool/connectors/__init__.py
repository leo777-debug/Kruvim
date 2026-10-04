from .environment import CalendarConnector, FxConnector, WeatherConnector
from .news import GdeltToneConnector, GoogleNewsConnector, RegionalTrendsConnector, WikipediaConnector
from .publisher_rss import PublisherRssConnector
from .social import BlueskyConnector, MastodonConnector, RedditConnector, XConnector, YouTubeConnector

ALL = [WeatherConnector(), GoogleNewsConnector(), GdeltToneConnector(), WikipediaConnector(), CalendarConnector(), FxConnector(),
       RegionalTrendsConnector(), MastodonConnector(), BlueskyConnector(), RedditConnector(), YouTubeConnector(), XConnector(), PublisherRssConnector()]
REGISTRY = {c.spec.key: c for c in ALL}
