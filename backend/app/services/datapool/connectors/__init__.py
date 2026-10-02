from .environment import CalendarConnector, FxConnector, WeatherConnector
from .news import GdeltToneConnector, GoogleNewsConnector, WikipediaConnector
from .social import BlueskyConnector, MastodonConnector, RedditConnector, XConnector, YouTubeConnector

ALL = [WeatherConnector(), GoogleNewsConnector(), GdeltToneConnector(), WikipediaConnector(), CalendarConnector(), FxConnector(),
       MastodonConnector(), BlueskyConnector(), RedditConnector(), YouTubeConnector(), XConnector()]
REGISTRY = {c.spec.key: c for c in ALL}
