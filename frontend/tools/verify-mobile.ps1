param([string]$Base = 'http://127.0.0.1:5174', [string]$ProjectId = '', [string]$RunId = '', [string]$Browser = 'agent-browser')
$ErrorActionPreference = 'Stop'
$routes = @('/', '/projects', '/data-pool', '/population', '/audiences', '/my-audience', '/monitoring', '/calibration', '/accuracy', '/settings', '/usage', '/admin')
if ($ProjectId) { $routes += @("/projects/$ProjectId", "/projects/$ProjectId/new") }
if ($RunId) { $routes += "/simulations/$RunId" }
& $Browser --session kruvim-gaps set viewport 390 844
foreach ($route in $routes) {
  & $Browser --session kruvim-gaps open "$Base$route" | Out-Null
  & $Browser --session kruvim-gaps wait 700 | Out-Null
  $script = @'
JSON.stringify({path:location.pathname,width:innerWidth,documentWidth:document.documentElement.scrollWidth,mainWidth:document.querySelector('main')?.clientWidth,mainScroll:document.querySelector('main')?.scrollWidth,signInLink:!!document.querySelector('a[href="/login"]'),accountRows:[...document.querySelectorAll('.account-table tr')].slice(1).map(r=>({display:getComputedStyle(r).display,width:r.getBoundingClientRect().width})),presetLabel:[...document.querySelectorAll('[role="combobox"]')].map(e=>document.getElementById(e.getAttribute('aria-labelledby'))?.textContent),nativeSelects:document.querySelectorAll('select:not([aria-hidden="true"])').length,developerText:document.body.innerText.includes('Retrieval: local-hash-v1')})
'@
  $raw = & $Browser --session kruvim-gaps eval $script
  if ($LASTEXITCODE) { throw "Browser check failed on $route" }
  $data = $raw | ConvertFrom-Json
  if ($data -is [string]) { $data = $data | ConvertFrom-Json }
  $data | ConvertTo-Json -Compress -Depth 5
  if ($data.documentWidth -gt 390 -or ($data.mainWidth -and $data.mainScroll -gt $data.mainWidth + 1)) { throw "Horizontal page scroll on $route" }
  if ($route -eq '/my-audience' -and ($data.accountRows | Where-Object display -ne 'block')) { throw 'Account cards are not stacked' }
  if ($route -eq '/accuracy' -and $data.signInLink) { throw 'Signed-in user sees sign-in link' }
  if ($route -eq '/monitoring' -and $data.nativeSelects) { throw 'Monitoring uses native selects' }
  if ($route.EndsWith('/new') -and 'Creator preset' -notin $data.presetLabel) { throw 'Creator preset has no accessible label' }
  if ($data.developerText) { throw 'Retrieval details leaked into overview' }
}


