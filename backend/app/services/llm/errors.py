"""Provider error contracts, distinct from temporary request throttling."""
import ipaddress
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from urllib.parse import urlparse

PROVIDERS = {
    'openai': {'label': 'OpenAI', 'billing_url': 'https://platform.openai.com/settings/organization/billing/overview'},
    'openrouter': {'label': 'OpenRouter', 'billing_url': 'https://openrouter.ai/settings/credits'},
    'deepseek': {'label': 'DeepSeek', 'billing_url': 'https://platform.deepseek.com/top_up'},
    'mistral': {'label': 'Mistral', 'billing_url': 'https://admin.mistral.ai/plateforme/billing'},
    'gemini': {'label': 'Google Gemini', 'billing_url': 'https://aistudio.google.com/usage'},
    'anthropic': {'label': 'Anthropic', 'billing_url': 'https://platform.claude.com/settings/billing'},
}
QUOTA_CODES = {'insufficient_quota', 'credit_balance_exhausted', 'organization_spend_limit_exceeded',
               'project_spend_limit_exceeded', 'organization_usage_limit_exceeded', 'usage_limit_exceeded',
               'quota_exceeded', 'billing_error', 'insufficient_balance', 'insufficient_credits'}


def provider_name(settings):
    host = urlparse(settings.base_url).hostname or ''
    for key in PROVIDERS:
        if key in settings.preset or key in host:
            return key
    if 'generativelanguage.googleapis.com' in host:
        return 'gemini'
    return settings.provider if settings.provider in PROVIDERS else 'custom'


def local_model(settings):
    if settings.preset in ('ollama', 'lmstudio', 'llamacpp', 'vllm'):
        return True
    host = urlparse(settings.base_url).hostname or ''
    if host in ('localhost', 'ollama', 'lmstudio') or host.endswith('.local'):
        return True
    try:
        return ipaddress.ip_address(host).is_private
    except ValueError:
        return False


@dataclass
class ClassifiedError:
    category: str
    retryable: bool
    provider: str


def classify(status, payload=None, *, settings=None, network_error=False):
    provider = provider_name(settings) if settings else 'custom'
    error = (payload or {}).get('error', payload or {}) if isinstance(payload, dict) else {}
    error = error if isinstance(error, dict) else {}
    codes = {str(error.get(field, '')).lower() for field in ('code', 'type', 'status')}
    message = str(error.get('message', '')).lower()
    details = error.get('details', [])
    quota_ids = ' '.join(str(violation.get(field, '')) for detail in details if isinstance(detail, dict)
        for violation in detail.get('violations', []) if isinstance(violation, dict)
        for field in ('quotaId', 'quotaMetric', 'description')).lower()
    per_minute = any(word in quota_ids for word in ('perminute', 'per_minute', 'persecond', 'per_second'))
    daily = any(word in quota_ids for word in ('perday', 'per_day', 'daily', 'permonth', 'per_month'))
    hard_balance = any(word in message for word in ('insufficient balance', 'insufficient credit', 'credit balance is too low',
        'credit balance exhausted', 'out of credit', 'monthly token limit', 'monthly usage limit', 'daily quota', 'daily limit',
        'spend limit', 'billing limit', 'billing hard limit'))
    quota = status == 402 or bool(codes & QUOTA_CODES) or daily or (hard_balance and not per_minute)
    if settings and local_model(settings):
        quota = False
    if network_error or status is None or status >= 500:
        category = 'provider_down'
    elif quota:
        category = 'quota_exhausted'
    elif status in (401, 403) or codes & {'authentication_error', 'invalid_api_key', 'api_key_invalid', 'unauthenticated'}:
        category = 'invalid_key'
    elif status == 429 or codes & {'rate_limit_error', 'rate_limited', 'rate_limit_exceeded', 'too_many_requests', 'resource_exhausted'}:
        category = 'rate_limited'
    else:
        category = 'request_error'
    return ClassifiedError(category, category in ('rate_limited', 'provider_down'), provider)


class ProviderFailure(Exception):
    def __init__(self, classified, raw=''):
        self.category, self.provider = classified.category, classified.provider
        self.raw = raw
        super().__init__('The model provider could not answer. Check its status in Settings.')


def retry_delay(headers, fallback):
    value = headers.get('retry-after', '')
    try:
        return max(0, float(value))
    except (TypeError, ValueError):
        try:
            return max(0, (parsedate_to_datetime(value) - datetime.now(UTC)).total_seconds())
        except (ValueError, TypeError, OverflowError):
            return fallback


class BudgetPause(BaseException):
    """A recoverable pause must bypass all deterministic agent/model fallbacks."""
    def __init__(self, state):
        self.state = state
        super().__init__(state['message'])
