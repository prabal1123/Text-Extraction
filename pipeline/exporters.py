import csv
import json
import openpyxl
from django.http import HttpResponse
from results.models import Result, Championship

def export_results_csv(queryset, filename="track_results.csv"):
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    
    writer = csv.writer(response)
    writer.writerow(['Championship', 'Communique', 'Category', 'Race Type', 'Rank', 'Bib', 'Rider', 'Team', 'Time (ms)', 'Speed', 'Points', 'Status'])
    
    for r in queryset:
        rider_name = r.rider.name if r.rider else "Team Event"
        team_name = r.team.name if r.team else ""
        writer.writerow([
            r.race.communique.championship.edition,
            r.race.communique.number,
            r.race.category,
            r.race.race_type,
            r.display_rank,
            r.bib or "",
            rider_name,
            team_name,
            r.time_ms or "",
            r.speed or "",
            r.points or "",
            r.status
        ])
    return response

def export_results_excel(queryset, filename="track_results.xlsx"):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Results"
    
    headers = ['Championship', 'Communique', 'Category', 'Race Type', 'Rank', 'Bib', 'Rider', 'Team', 'Time (ms)', 'Speed', 'Points', 'Status']
    ws.append(headers)
    
    for r in queryset:
        rider_name = r.rider.name if r.rider else "Team Event"
        team_name = r.team.name if r.team else ""
        ws.append([
            r.race.communique.championship.edition,
            r.race.communique.number or "",
            r.race.category,
            r.race.race_type,
            r.display_rank,
            r.bib or "",
            rider_name,
            team_name,
            r.time_ms or "",
            r.speed or "",
            r.points or "",
            r.status
        ])
        
    response = HttpResponse(content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    wb.save(response)
    return response

def export_results_json(queryset):
    data = []
    for r in queryset:
        data.append({
            'championship': r.race.communique.championship.edition,
            'communique': r.race.communique.number,
            'category': r.race.category,
            'race_type': r.race.race_type,
            'rank': r.display_rank,
            'bib': r.bib,
            'rider': r.rider.name if r.rider else None,
            'team': r.team.name if r.team else None,
            'time_ms': r.time_ms,
            'speed': r.speed,
            'points': r.points,
            'status': r.status
        })
    return HttpResponse(json.dumps(data, indent=2), content_type='application/json')
