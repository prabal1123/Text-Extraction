import yaml
import os
from results.models import Result, Team, Rider

def load_team_aliases():
    path = 'layouts/teams_alias.yaml'
    if not os.path.exists(path): return {}
    with open(path, 'r') as f:
        data = yaml.safe_load(f)
        mapping = {}
        for canonical, variants in data.get('aliases', {}).items():
            for v in variants:
                mapping[v.lower()] = canonical
        return mapping

def normalize_database():
    aliases = load_team_aliases()
    
    # 1. Normalize Team Names
    for team in Team.objects.all():
        clean_name = team.name.strip()
        canonical = aliases.get(clean_name.lower())
        if canonical and canonical != team.name:
            target_team, _ = Team.objects.get_or_create(name=canonical)
            # Reassign results and team members
            for res in team.results.all():
                res.team = target_team
                res.save()
            if team.id != target_team.id:
                team.delete()

    print("Team normalization complete.")
