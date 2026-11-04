"""Explicit column mappings, native aggregate data and private creator baselines."""
import hashlib
import math
import re
from collections import defaultdict
from datetime import UTC, datetime
from difflib import SequenceMatcher
from statistics import median
from zoneinfo import ZoneInfo

from sqlalchemy import delete, select

from app.core.errors import NotFound
from app.models import AnalyticsImport, ImportedAnalyticsPost, Organization, PerformanceReport, Simulation
from app.schemas.creator import FollowerSplit
from app.services.sources.adapters import table

METRICS = ('views', 'likes', 'comments', 'shares', 'saves', 'reach', 'avg_watch_time', 'completion', 'retention')
POST_FIELDS = ('published_at', 'caption', 'post_id', 'format', 'length_seconds', 'hook_style', *METRICS)
DIMENSIONS = ('countries', 'cities', 'ages', 'genders', 'active_hours')


def inspect_file(raw, filename):
    headers, rows = table(raw, filename)
    if len(rows) > 10000:
        raise ValueError('Import up to 10,000 rows at a time; split larger exports into files')
    for header in headers:
        normalized = re.sub(r'[^a-z]', '', header.lower())
        if normalized in ('email', 'phone', 'username', 'handle', 'followername', 'followerid', 'firstname', 'lastname',
                          'fullname', 'name', 'commenter', 'commenttext', 'contact', 'accountname', 'userid') or (
                              normalized.startswith(('follower', 'viewer', 'commenter')) and
                              any(identifier in normalized for identifier in ('name', 'handle', 'email', 'phone', 'id'))):
            raise ValueError('Only aggregate analytics are accepted. Remove follower identities, contacts and individual comments before uploading.')
    if any(re.search(r'[\w.+-]+@[\w.-]+\.[a-zA-Z]{2,}', str(value or '')) for row in rows for value in row.values()):
        raise ValueError('The file contains contact details. Upload aggregate analytics only.')
    return headers, rows


def number(value, *, percent=False, unit='percent', duration=False):
    if value is None or str(value).strip() in ('', 'N/A', 'NA', '--', '-'):
        return None
    text = str(value).strip()
    if duration and ':' in text:
        pieces = text.split(':')
        if len(pieces) not in (2, 3):
            raise ValueError('Watch time must be seconds or mm:ss / hh:mm:ss')
        result = sum(float(part) * 60 ** i for i, part in enumerate(reversed(pieces)))
    else:
        result = float(text.replace(',', '').rstrip('%'))
        if percent and unit == 'fraction':
            result *= 100
    if not math.isfinite(result) or result < 0:
        raise ValueError('Analytics values must be finite and nonnegative')
    return result


def parse(raw, filename, kind, mapping):
    headers, rows = inspect_file(raw, filename)
    columns = mapping.get('columns', {})
    allowed = POST_FIELDS if kind == 'posts' else ('category', 'value', 'dimension')
    if set(columns) - set(allowed) or any(column not in headers for column in columns.values()):
        raise ValueError('Choose valid columns from the uploaded file')
    if kind == 'posts':
        if 'published_at' not in columns or not any(field in columns for field in METRICS):
            raise ValueError('Map the post date and at least one performance metric')
        parsed = []
        for index, row in enumerate(rows, 2):
            try:
                def get(key, cells=row):
                    return cells.get(columns.get(key))
                text = str(get('published_at') or '').strip()
                date_format = mapping.get('date_format', 'iso')
                published = datetime.fromisoformat(text.replace('Z', '+00:00')) if date_format == 'iso' else datetime.strptime(text, date_format)
                if not published.tzinfo:
                    published = published.replace(tzinfo=ZoneInfo(mapping.get('timezone', 'UTC')))
                metrics = {key: number(get(key), percent=key in ('retention', 'completion'),
                    unit=mapping.get('percentage_unit', 'percent'), duration=key == 'avg_watch_time') for key in METRICS if key in columns}
                metrics = {key: value for key, value in metrics.items() if value is not None}
                for key, value in metrics.items():
                    if key in ('views', 'likes', 'comments', 'shares', 'saves', 'reach') and not value.is_integer():
                        raise ValueError(f'{key} must be a whole count')
                    if key == 'completion' and value > 100:
                        raise ValueError('Completion must be between 0 and 100 percent')
                metrics = {key: int(value) if key in ('views', 'likes', 'comments', 'shares', 'saves', 'reach') else value for key, value in metrics.items()}
                if not metrics:
                    raise ValueError('This row has no observed metrics')
                parsed.append({'published_at': published.astimezone(UTC), 'caption': str(get('caption') or '')[:60000],
                    'format': str(get('format') or mapping.get('format') or 'unknown')[:40], 'post_id': str(get('post_id') or '')[:200],
                    'metrics': metrics, 'metadata_fields': {'length_seconds': number(get('length_seconds')),
                        'hook_style': str(get('hook_style') or '')[:200], 'reported_window': mapping.get('reported_window', 'unspecified')}})
            except (ValueError, TypeError, KeyError) as exc:
                raise ValueError(f'Row {index}: {exc}') from exc
        return {'posts': parsed, 'row_count': len(parsed)}
    if not {'category', 'value'} <= set(columns):
        raise ValueError('Map the category and its count or percentage')
    bins = defaultdict(dict)
    for index, row in enumerate(rows, 2):
        dimension = str(row.get(columns.get('dimension')) or mapping.get('dimension') or '')
        if dimension not in DIMENSIONS:
            raise ValueError(f'Row {index}: choose countries, cities, ages, genders or active_hours')
        category = str(row.get(columns['category']) or '').strip()
        category = str(mapping.get('category_map', {}).get(category, category)).replace('–', '-')
        if dimension == 'genders':
            category = {'women': 'female', 'men': 'male'}.get(category.lower(), category.lower())
        if dimension == 'countries':
            category = category.upper()
        value = number(row.get(columns['value']), percent=True)
        if not category or len(category) > 200 or value is None:
            raise ValueError(f'Row {index}: missing or invalid aggregate category/value')
        if category in bins[dimension]:
            raise ValueError(f'Row {index}: duplicate category; use one breakdown snapshot per file')
        bins[dimension][category] = value
    unit = mapping.get('audience_unit', 'percent')
    if unit not in ('count', 'percent'):
        raise ValueError('Audience values must be counts or percentages')
    if unit == 'count' and any(not value.is_integer() for values in bins.values() for value in values.values()):
        raise ValueError('Follower counts must be whole numbers')
    split, gaps = {}, []
    for dimension, values in bins.items():
        total = sum(values.values())
        if not total or (unit == 'count' and not mapping.get('complete_distribution')) or (unit == 'percent' and abs(total - 100) > 1):
            gaps.append(f'{dimension}: incomplete breakdown; retained for display, excluded from audience matching')
            continue
        percentages = {key: round(value * 100 / total, 6) for key, value in values.items()}
        if dimension in ('countries', 'ages', 'genders', 'cities'):
            try:
                FollowerSplit.model_validate({dimension: percentages})
                split[dimension] = percentages
            except ValueError:
                gaps.append(f'{dimension}: map categories to supported country codes, age bands or genders before matching')
    return {'audience': dict(bins), 'unit': unit, 'split': split, 'coverage_gaps': gaps, 'row_count': len(rows)}


async def own_import(s, org_id, import_id):
    row = (await s.execute(select(AnalyticsImport).where(AnalyticsImport.org_id == org_id, AnalyticsImport.id == import_id).with_for_update())).scalar_one_or_none()
    if not row:
        raise NotFound('Analytics import not found in this workspace')
    return row


async def apply(s, row, parsed):
    if row.status == 'applied':
        return row.summary
    await s.execute(select(Organization.id).where(Organization.id == row.org_id).with_for_update())
    inserted = updated = 0
    for post in parsed.get('posts', []):
        identity = post.pop('post_id') or f"{post['published_at'].isoformat()}:{post['caption']}:{post['format']}"
        fingerprint = hashlib.sha256(f'{row.platform}:{identity}'.encode()).hexdigest()
        existing = (await s.execute(select(ImportedAnalyticsPost).where(ImportedAnalyticsPost.org_id == row.org_id,
            ImportedAnalyticsPost.fingerprint == fingerprint).with_for_update())).scalar_one_or_none()
        if existing:
            # New metrics retain unavailable older fields; identical files cannot duplicate posts.
            existing.metrics = {**existing.metrics, **post['metrics']}
            existing.metadata_fields = post['metadata_fields']
            existing.import_id = row.id
            updated += 1
            if existing.simulation_id:
                await outcome(s, existing)
        else:
            s.add(ImportedAnalyticsPost(org_id=row.org_id, import_id=row.id, platform=row.platform, fingerprint=fingerprint, **post))
            inserted += 1
    row.summary = {key: value for key, value in parsed.items() if key != 'posts'} | {'inserted': inserted, 'updated': updated}
    row.status = 'applied'
    if parsed.get('split'):
        org = (await s.execute(select(Organization).where(Organization.id == row.org_id).with_for_update())).scalar_one()
        current = (org.settings or {}).get('creator_audience', {})
        previous = current.get('split', {}) if current.get('platform') == row.platform and current.get('source') == 'analytics_import' else {}
        org.settings = {**(org.settings or {}), 'creator_audience': {'label': 'My imported audience', 'source': 'analytics_import',
            'platform': row.platform, 'import_id': row.id, 'split': {**previous, **parsed['split']},
            'coverage_gaps': parsed.get('coverage_gaps', []), 'filters': {}}}
    await s.flush()
    return row.summary


async def outcome(s, post):
    report = (await s.execute(select(PerformanceReport).where(PerformanceReport.org_id == post.org_id,
        PerformanceReport.analytics_post_id == post.id))).scalar_one_or_none()
    if not report:
        report = PerformanceReport(org_id=post.org_id, simulation_id=post.simulation_id, analytics_post_id=post.id,
            platform=post.platform, variant=post.variant, notes='Creator-imported aggregate analytics; observation window supplied by the creator.')
        s.add(report)
    report.simulation_id, report.variant = post.simulation_id, post.variant
    for metric in ('views', 'likes', 'comments', 'shares', 'retention'):
        setattr(report, metric, post.metrics.get(metric))
    denominator = post.metrics.get('views') or post.metrics.get('reach')
    report.engagement_rate = 100 * sum(post.metrics.get(key, 0) for key in ('likes', 'comments', 'shares')) / denominator if denominator else None


def baseline(posts):
    values = {key: [p.metrics[key] for p in posts if p.metrics.get(key) is not None] for key in METRICS}
    return {'n': len(posts), 'medians': {key: median(items) for key, items in values.items() if items},
            'samples': {key: len(items) for key, items in values.items() if items}}


def prediction(sim, variant='A'):
    results = sim.results or {}
    if variant == 'B':
        heatmap = (results.get('ab') or {}).get('b_heatmap') or []
        share = (results.get('ab') or {}).get('b', {}).get('would_share')
        completion = (results.get('ab') or {}).get('b', {}).get('completion')
    else:
        heatmap = (results.get('heatmap') or {}).get('segments', [])
        share = (results.get('viral') or {}).get('raw', {}).get('mean_share_intent')
        completion = (results.get('heatmap') or {}).get('completion')
    durations = [max(.01, segment.get('end', 1) - segment.get('start', 0)) if segment.get('end') is not None and segment.get('start') is not None else 1 for segment in heatmap]
    average = sum(float(segment.get('retention', 0)) * length for segment, length in zip(heatmap, durations)) / sum(durations) if durations else None
    return {'dry': results.get('provider', {}).get('dry', True), 'finished_at': sim.finished_at.isoformat() if sim.finished_at else None,
        'share_intent': share, 'completion': completion * 100 if completion is not None else None,
        'retention': average * 100 if average is not None else None,
        'views': results.get('creator_analytics', {}).get('forecast', {}).get('views') if variant == 'A' else None}


def comparable(post):
    predicted_at = post.prediction.get('finished_at')
    return bool(predicted_at and not post.prediction.get('dry', True) and datetime.fromisoformat(predicted_at) < post.published_at)


def calibration(posts):
    pairs = defaultdict(list)
    for post in sorted(posts, key=lambda p: p.published_at, reverse=True):
        if not comparable(post):
            continue
        for metric in ('views', 'completion', 'retention'):
            actual, predicted = post.metrics.get(metric), post.prediction.get(metric)
            if actual is not None and predicted is not None and len(pairs[metric]) < 5:
                error = abs(actual - predicted) / actual * 100 if metric == 'views' and actual > 0 else abs(actual - predicted)
                if metric == 'views' and actual <= 0:
                    continue
                pairs[metric].append({'post_id': post.id, 'simulation_id': post.simulation_id, 'actual': actual, 'predicted': predicted, 'error': error})
    return {metric: {'n': len(rows), 'mean_absolute_error': round(sum(row['error'] for row in rows) / len(rows), 2),
        'unit': 'percent of actual views' if metric == 'views' else 'percentage points', 'rows': rows} for metric, rows in pairs.items()}


async def summary(s, org_id, platform=None):
    query = select(ImportedAnalyticsPost).where(ImportedAnalyticsPost.org_id == org_id)
    if platform:
        query = query.where(ImportedAnalyticsPost.platform == platform)
    posts = (await s.execute(query.order_by(ImportedAnalyticsPost.published_at.desc()).limit(20000))).scalars().all()
    groups = defaultdict(list)
    for post in posts:
        groups[post.platform].append(post)
    observed = [post for post in posts if post.metrics.get('views') is not None]
    best = sorted(observed, key=lambda p: p.metrics['views'], reverse=True)[:max(1, math.ceil(len(observed) / 4))]
    patterns = []
    for dimension in ('format', 'length_seconds', 'hook_style', 'hour'):
        bins = defaultdict(list)
        for post in best:
            value = post.format if dimension == 'format' else post.published_at.hour if dimension == 'hour' else post.metadata_fields.get(dimension)
            if value is not None and value != '' and value != 'unknown':
                bins[str(value)].append(post.metrics['views'])
        patterns.extend({'dimension': dimension, 'value': value, 'n': len(values), 'median_views': median(values)} for value, values in bins.items())
    return {'baseline': baseline(posts), 'platforms': {key: baseline(rows) for key, rows in groups.items()},
        'patterns': patterns, 'calibration': calibration(posts), 'linked': sum(bool(p.simulation_id) for p in posts),
        'method': 'Private reported aggregates. Missing fields stay missing. Best-post patterns are descriptive, not causal; posting hours are UTC. Report windows can differ.'}


async def forecast(s, org_id, platform, share):
    posts = (await s.execute(select(ImportedAnalyticsPost).where(ImportedAnalyticsPost.org_id == org_id,
        ImportedAnalyticsPost.platform == platform))).scalars().all()
    ratios = [post.metrics['views'] / post.prediction['share_intent'] for post in posts if comparable(post)
        and post.metrics.get('views') is not None and post.prediction.get('share_intent', 0) > 0]
    base = baseline(posts)
    if len(ratios) < 3 or share is None:
        return {'baseline': base, 'forecast': {}, 'method': 'A relative view forecast needs three linked model predictions made before publication on this platform.'}
    views = round(median(ratios) * share)
    usual = base['medians'].get('views')
    return {'baseline': base, 'forecast': {'views': views, 'usual_multiple': round(views / usual, 2) if usual else None, 'calibration_n': len(ratios)},
        'method': 'Median actual views / predicted share intent from prior linked posts, multiplied by this test’s share intent. Same platform, reported observation windows; uncertain observational estimate.'}


async def suggestions(s, org_id, post):
    sims = (await s.execute(select(Simulation).where(Simulation.org_id == org_id, Simulation.status == 'completed',
        Simulation.content['platform'].as_string() == post.platform).order_by(Simulation.created_at.desc()).limit(200))).scalars().all()
    candidates = []
    for sim in sims:
        caption = str(sim.content.get('title') or sim.content.get('text') or sim.content.get('transcript') or sim.name)
        similarity = SequenceMatcher(None, caption.lower()[:500], post.caption.lower()[:500]).ratio()
        days = abs((post.published_at - (sim.finished_at or sim.created_at)).total_seconds()) / 86400
        candidates.append({'simulation_id': sim.id, 'name': sim.name, 'caption_similarity': round(similarity, 3),
            'days_apart': round(days, 1), 'has_variant_b': bool(sim.content.get('variant_b')), 'rank': similarity + .2 / (1 + days)})
    return sorted(candidates, key=lambda item: -item['rank'])[:5]


async def remove_all(s, org):
    imports = (await s.execute(select(AnalyticsImport).where(AnalyticsImport.org_id == org.id))).scalars().all()
    await s.execute(delete(PerformanceReport).where(PerformanceReport.org_id == org.id, PerformanceReport.analytics_post_id.is_not(None)))
    await s.execute(delete(ImportedAnalyticsPost).where(ImportedAnalyticsPost.org_id == org.id))
    from app.models import AnalyticsMappingPreset
    await s.execute(delete(AnalyticsMappingPreset).where(AnalyticsMappingPreset.org_id == org.id))
    await s.execute(delete(AnalyticsImport).where(AnalyticsImport.org_id == org.id))
    profile = (org.settings or {}).get('creator_audience') or {}
    if profile.get('source') == 'analytics_import':
        org.settings = {key: value for key, value in (org.settings or {}).items() if key != 'creator_audience'}
    sims = (await s.execute(select(Simulation).where(Simulation.org_id == org.id))).scalars().all()
    for sim in sims:
        if 'creator_analytics' in (sim.results or {}):
            sim.results = {key: value for key, value in sim.results.items() if key != 'creator_analytics'}
    return [row.storage_key for row in imports if row.storage_key]
