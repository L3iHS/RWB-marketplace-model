param(
    [string]$Url = 'http://localhost:3000',
    [int]$DatabaseId = 0,
    [switch]$ValidateOnly
)
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$questions = Join-Path $root 'metabase/questions'
$definitions = @(
    @('01_revenue.sql', 'Товарный оборот · BRL', 'scalar', 0, 0, 8, 4),
    @('02_orders.sql', 'Доставленные заказы', 'scalar', 0, 8, 8, 4),
    @('03_average_check.sql', 'Средний чек с доставкой · BRL', 'scalar', 0, 16, 8, 4),
    @('04_monthly.sql', 'Оборот по месяцам · BRL', 'bar', 4, 0, 12, 7),
    @('04_monthly.sql', 'Заказы по месяцам', 'line', 4, 12, 12, 7),
    @('05_sellers.sql', 'Топ-10 продавцов', 'table', 11, 0, 12, 8),
    @('06_categories.sql', 'Категории и доли оборота', 'table', 11, 12, 12, 8),
    @('07_orders_detail.sql', 'Детализация доставленных заказов', 'table', 19, 0, 24, 9),
    @('08_quality.sql', 'Качество данных · весь набор, без фильтра периода', 'table', 28, 0, 24, 7)
)
foreach ($definition in $definitions) {
    if (!(Test-Path (Join-Path $questions $definition[0]))) { throw "Missing SQL: $($definition[0])" }
}
if ($ValidateOnly) { Write-Output "Validated $($definitions.Count) card definitions and SQL file paths."; exit 0 }
$Url = $Url.TrimEnd('/')
$headers = @{}
function Api($method, $path, $body = $null) {
    $args = @{ Method=$method; Uri="$Url/api/$path"; Headers=$headers; TimeoutSec=120 }
    if ($null -ne $body) {
        $args.ContentType = 'application/json; charset=utf-8'
        $args.Body = [Text.Encoding]::UTF8.GetBytes(($body | ConvertTo-Json -Depth 40))
    }
    Invoke-RestMethod @args
}
$health = Api GET 'health'
if ($health.status -ne 'ok') { throw 'Metabase is not ready.' }
$credential = Get-Credential -Message 'Metabase: email and password of your existing account'
if ($null -eq $credential) { throw 'Login cancelled.' }
$session = Api POST 'session' @{username=$credential.UserName; password=$credential.GetNetworkCredential().Password}
$headers['X-Metabase-Session'] = $session.id
try {
    if (!$DatabaseId) {
        $databases = (Api GET 'database').data | Where-Object { $_.engine -eq 'postgres' -and $_.details.dbname -eq 'marketplace' }
        if (@($databases).Count -ne 1) { throw 'Specify -DatabaseId from the Marketplace database settings URL.' }
        $DatabaseId = @($databases)[0].id
    }
    $collectionName = 'Capibara · Аналитика продаж v1'
    $existing = @(Api GET 'collection') | Where-Object { $_.name -eq $collectionName -and !$_.archived }
    if ($existing) { throw 'Dashboard collection already exists. Edit it in Metabase; this script will not overwrite it or create duplicates.' }
    $collection = Api POST 'collection' @{name=$collectionName; description='Продажи доставленных заказов по дате оформления. Денежные значения в BRL.'}
    $parameters = @(
        @{id='date_from'; name='Дата с'; slug='date_from'; type='date/single'},
        @{id='date_to'; name='Дата по'; slug='date_to'; type='date/single'},
        @{id='customer_state'; name='Штат покупателя'; slug='customer_state'; type='string/='}
    )
    $dashboard = Api POST 'dashboard' @{
        name='Capibara · Анализ продаж'; collection_id=$collection.id
        description='Доставленные заказы по дате оформления. Оборот без доставки; средний чек с доставкой. Качество данных относится ко всему набору. NULL среднего чека означает отсутствие известных сумм.'
        parameters=$parameters
    }
    Write-Output "Created dashboard: $Url/dashboard/$($dashboard.id)"
    $dashcards = @()
    $index = 0
    foreach ($definition in $definitions) {
        $index++
        $sql = Get-Content -Raw -Encoding UTF8 (Join-Path $questions $definition[0])
        $tags = @{}
        $mappings = @()
        $filtered = $definition[0] -ne '08_quality.sql'
        if ($filtered) {
            foreach ($parameter in $parameters) {
                $key = $parameter.id
                $tags[$key] = @{id=[guid]::NewGuid().ToString(); name=$key; 'display-name'=$parameter.name; type=$(if ($key -eq 'customer_state') {'text'} else {'date'}); required=$false}
            }
        }
        $settings = @{}
        if ($definition[2] -in @('bar','line')) {
            $settings['graph.dimensions'] = @('month')
            $settings['graph.metrics'] = @($(if ($definition[2] -eq 'bar') {'revenue_brl'} else {'delivered_orders'}))
        }
        $card = Api POST 'card' @{
            name=$definition[1]; collection_id=$collection.id; display=$definition[2]; visualization_settings=$settings
            dataset_query=@{database=$DatabaseId; type='native'; native=@{query=$sql; 'template-tags'=$tags}}
        }
        if ($filtered) {
            foreach ($parameter in $parameters) {
                $mappings += @{parameter_id=$parameter.id; card_id=$card.id; target=@('variable', @('template-tag', $parameter.id))}
            }
        }
        $dashcards += @{id=-$index; card_id=$card.id; row=$definition[3]; col=$definition[4]; size_x=$definition[5]; size_y=$definition[6]; parameter_mappings=$mappings; visualization_settings=@{}}
        # Save each addition so a partial failure leaves the completed cards visible.
        $updated = Api PUT "dashboard/$($dashboard.id)" @{dashcards=$dashcards}
        $dashcards = @($updated.dashcards)
    }
    Write-Output "Ready: $Url/dashboard/$($dashboard.id)"
} finally {
    try { Api DELETE 'session' | Out-Null } catch { Write-Warning 'Could not close Metabase session.' }
}