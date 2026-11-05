import os
import re
import hashlib
import pdfplumber
from django.shortcuts import render, redirect
from django.contrib import messages
from django.db.models import Q
from .forms import ChampionshipUploadForm
from .models import Championship, Communique, Race
from pipeline.segmenter import segment_pdf
from pipeline.parsers import parse_pdf_tables, parse_team_events, parse_time_to_ms, extract_status
from pipeline.quality import normalize_dob, parse_rows, parse_team_blocks, total_points
from pipeline.medalist_parser import parse_medalist_pdf
from results.models import Result, Rider, Team, TeamMember, PointsDetail
from pipeline.exporters import export_results_csv, export_results_excel, export_results_json

def results_browse_view(request):
    query = request.GET.get('q', '')
    champ_id = request.GET.get('champ', '')
    race_type_filter = request.GET.get('race_type', '')
    category_filter = request.GET.get('category', '')
    rank_filter = request.GET.get('rank', '')
    format_type = request.GET.get('format', '')
    
    results = Result.objects.select_related('race__communique__championship', 'rider', 'team').all()
    
    if query:
        results = results.filter(
            Q(rider__name__icontains=query) | 
            Q(team__name__icontains=query) | 
            Q(race__race_type__icontains=query)
        )
        
    if champ_id:
        results = results.filter(race__communique__championship_id=champ_id)
        
    if race_type_filter:
        results = results.filter(race__race_type__icontains=race_type_filter)
        
    if category_filter:
        results = results.filter(race__category__icontains=category_filter)
        
    if rank_filter:
        results = results.filter(display_rank__iexact=rank_filter)
        
    if format_type == 'csv':
        return export_results_csv(results)
    elif format_type == 'xlsx':
        return export_results_excel(results)
    elif format_type == 'json':
        return export_results_json(results)
        
    championships = Championship.objects.all()
    race_types = Race.objects.values_list('race_type', flat=True).distinct().order_by('race_type')
    categories = Race.objects.values_list('category', flat=True).distinct().order_by('category')
    
    context = {
        'results': results[:100],
        'championships': championships,
        'race_types': race_types,
        'categories': categories,
        'query': query,
        'selected_champ': champ_id,
        'selected_race_type': race_type_filter,
        'selected_category': category_filter,
        'selected_rank': rank_filter,
    }
    return render(request, 'results/browse.html', context)

def races_list_view(request):
    champ_id = request.GET.get('champ', '')
    layout_filter = request.GET.get('layout', '')
    
    races = Race.objects.select_related('communique__championship').all()
    if champ_id:
        races = races.filter(communique__championship_id=champ_id)
    if layout_filter:
        races = races.filter(layout_family=layout_filter)
        
    championships = Championship.objects.all()
    context = {
        'races': races,
        'championships': championships,
        'selected_champ': champ_id,
        'selected_layout': layout_filter,
    }
    return render(request, 'results/races.html', context)

def rank_to_numeric(display_rank):
    d = (display_rank or "").strip()
    if d.isdigit():
        return int(d)
    return {"gold": 1, "silver": 2, "bronze": 3}.get(d.lower())

def first_val(row, base):
    for key in (base, base + "_2", base + "_3"):
        v = row.get(key)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ""

def status_cells(row):
    cells = [first_val(row, "rank"), first_val(row, "time"), first_val(row, "speed")]
    cells += [v for k, v in row.items() if k.startswith(("x_rem", "remark")) and isinstance(v, str)]
    return cells

def upload_pdf_view(request):
    if request.method == 'POST':
        form = ChampionshipUploadForm(request.POST, request.FILES)
        if form.is_valid():
            pdf_file = request.FILES['pdf_file']
            filename = pdf_file.name
            
            hasher = hashlib.sha256()
            file_bytes = b''
            for chunk in pdf_file.chunks():
                file_bytes += chunk
                hasher.update(chunk)
            pdf_hash = hasher.hexdigest()
            
            os.makedirs('.cache/pdfs', exist_ok=True)
            pdf_path = f".cache/pdfs/{pdf_hash}.pdf"
            with open(pdf_path, 'wb+') as destination:
                destination.write(file_bytes)
                
            edition = form.cleaned_data.get('edition')
            year = form.cleaned_data.get('year')
            venue = form.cleaned_data.get('venue') or "National Velodrome"
            source_url = form.cleaned_data.get('source_url') or "Local Upload"
            
            with pdfplumber.open(pdf_path) as pdf:
                first_page_text = pdf.pages[0].extract_text() or ""
                if not edition:
                    ed_match = re.search(r'(\d{1,2})(?:st|nd|rd|th)\s+(?:Hero|National|Cycling|Medalist)?', first_page_text, re.I)
                    edition = int(ed_match.group(1)) if ed_match else 72
                if not year:
                    yr_match = re.search(r'\b(20\d{2})\b', first_page_text)
                    year = int(yr_match.group(1)) if yr_match else 2022

            champ = Championship.objects.filter(pdf_hash=pdf_hash).first()
            if not champ:
                champ, _ = Championship.objects.update_or_create(
                    edition=edition,
                    defaults={'year': year, 'venue': venue, 'source_url': source_url, 'pdf_hash': pdf_hash}
                )
            
            is_medalist_doc = "medalist" in filename.lower() or "medalist" in first_page_text.lower()
            
            if is_medalist_doc:
                comm_obj, _ = Communique.objects.get_or_create(
                    championship=champ,
                    number=None,
                    page_range='1-5',
                    defaults={'raw_header_text': 'Consolidated Medalist Summary'}
                )
                race_obj, _ = Race.objects.get_or_create(
                    communique=comm_obj,
                    defaults={'category': 'Consolidated Medalists', 'race_type': 'Championship Medal Summary', 'gender': 'Men/Women', 'layout_family': 'placing'}
                )
                parsed_count, skipped_count = parse_medalist_pdf(pdf_path, race_obj)
                messages.success(request, f"Successfully parsed {parsed_count} medalist records ({skipped_count} duplicates skipped) for the {champ.edition}th Championship!")
                return redirect('browse_results')
            
            communiques_data = segment_pdf(pdf_path)
            created_races_count = 0
            
            for comm_data in communiques_data:
                header_text = comm_data['header_text']
                full_text = comm_data['full_text']
                pages = comm_data['pages']
                page_range = f"{pages[0]}-{pages[-1]}" if len(pages) > 1 else str(pages[0])
                
                comm_num = None
                match = re.search(r'(?:Communique|No\.?|No\s*:)\s*(\d+)', header_text, re.I)
                if match:
                    comm_num = int(match.group(1))
                    
                comm_obj, _ = Communique.objects.get_or_create(
                    championship=champ,
                    number=comm_num,
                    page_range=page_range,
                    defaults={'raw_header_text': header_text}
                )
                comm_obj.raw_header_text = header_text
                comm_obj.save()
                
                layout_family = 'unknown'
                text_lower = full_text.lower()
                if 'team sprint' in text_lower or 'team pursuit' in text_lower:
                    layout_family = 'team'
                elif 'points race' in text_lower or 'madison' in text_lower or 'omnium' in text_lower:
                    layout_family = 'points'
                elif any(w in text_lower for w in ['time trial', 'pursuit', 'start no', 'time']):
                    layout_family = 'timed'
                elif any(w in text_lower for w in ['sprint', 'keirin', 'scratch', 'elimination', 'rank']):
                    layout_family = 'placing'
                    
                race_obj, _ = Race.objects.get_or_create(
                    communique=comm_obj,
                    defaults={'category': 'Elite / Junior', 'race_type': 'Extracted Race', 'gender': 'Men/Women', 'layout_family': layout_family}
                )
                
                if race_obj.layout_family in ['timed', 'placing', 'team', 'points']:
                    if race_obj.layout_family == 'team':
                        blocks = parse_team_blocks(pdf_path, pages)
                        for block in blocks:
                            display_rank = block['rank']
                            numeric_rank = rank_to_numeric(display_rank)
                            team_obj = Team.objects.get_or_create(name=block['team'])[0] if block['team'] else None
                            
                            # Check if team result exists
                            if Result.objects.filter(race=race_obj, team=team_obj, display_rank=display_rank).exists():
                                continue
                                
                            result = Result.objects.create(
                                race=race_obj, rider=None, team=team_obj, display_rank=display_rank,
                                numeric_rank=numeric_rank, status=block['status'], bib=None,
                                time_ms=parse_time_to_ms(block['time']), speed=block['speed'],
                                raw_row=block, needs_review=(block['status'] != 'OK' and not numeric_rank)
                            )
                            for m in block['members']:
                                if m['name'].strip():
                                    dob_val, _ = normalize_dob(m['dob'])
                                    rider_obj = Rider.objects.filter(name=m['name'].strip()).first()
                                    if not rider_obj:
                                        rider_obj = Rider.objects.create(name=m['name'].strip(), dob=dob_val, gender=race_obj.gender)
                                    TeamMember.objects.create(result=result, rider=rider_obj, is_reserve=m['is_reserve'])
                    else:
                        rows, info = parse_rows(pdf_path, pages, race_obj.layout_family, race_obj.race_type)
                        for row in rows:
                            status = extract_status(status_cells(row))
                            display_rank = first_val(row, 'rank')
                            numeric_rank = rank_to_numeric(display_rank)
                            team_name = (row.get('team') or '').strip()
                            team_obj = Team.objects.get_or_create(name=team_name)[0] if team_name else None
                            
                            name = (row.get('name') or '').strip()
                            rider_obj = None
                            if name:
                                dob_val, _ = normalize_dob(row.get('dob'))
                                rider_obj = Rider.objects.filter(name=name).first()
                                if not rider_obj:
                                    rider_obj = Rider.objects.create(name=name, dob=dob_val, gender=race_obj.gender)
                            
                            # Skip if result already exists
                            if Result.objects.filter(race=race_obj, rider=rider_obj, display_rank=display_rank).exists():
                                continue
                                
                            Result.objects.create(
                                race=race_obj, rider=rider_obj, team=team_obj, display_rank=display_rank,
                                numeric_rank=numeric_rank, status=status, bib=first_val(row, 'bib'),
                                time_ms=parse_time_to_ms(first_val(row, 'time')), speed=first_val(row, 'speed'),
                                points=total_points(row), raw_row=row,
                                needs_review=(status != 'OK' and not numeric_rank)
                            )

                created_races_count += 1
                
            messages.success(request, f"Successfully uploaded, parsed, and ingested {created_races_count} communiques with duplicate checking enabled!")
            return redirect('browse_results')
    else:
        form = ChampionshipUploadForm()
    return render(request, 'results/upload.html', {'form': form})
