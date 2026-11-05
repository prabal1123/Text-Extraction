from django.db import models

class Championship(models.Model):
    edition = models.IntegerField(unique=True)
    year = models.IntegerField(null=True, blank=True)
    venue = models.CharField(max_length=255, null=True, blank=True)
    source_url = models.URLField(max_length=500)
    pdf_hash = models.CharField(max_length=64, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.edition}th Track Cycling Championship ({self.year or 'Unknown Year'})"

class ImportRun(models.Model):
    championship = models.ForeignKey(Championship, on_delete=models.CASCADE, related_name='import_runs')
    timestamp = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=50)
    log = models.TextField(blank=True)

    def __str__(self):
        return f"Run {self.id} for {self.championship.edition}th ({self.status})"
class Communique(models.Model):
    championship = models.ForeignKey(Championship, on_delete=models.CASCADE, related_name='communiques')
    number = models.CharField(max_length=50, blank=True, null=True)
    page_range = models.CharField(max_length=50)
    race_date = models.CharField(max_length=100, blank=True, null=True) # Storing as string for now due to varied formats
    raw_header_text = models.TextField()

    def __str__(self):
        return f"Comm. {self.number or 'Unnumbered'} (Pages {self.page_range})"

class Race(models.Model):
    communique = models.ForeignKey(Communique, on_delete=models.CASCADE, related_name='races')
    race_type = models.CharField(max_length=100)
    category = models.CharField(max_length=100)
    age_group = models.CharField(max_length=50)
    gender = models.CharField(max_length=50)
    stage = models.CharField(max_length=100, blank=True, null=True)
    distance = models.CharField(max_length=100, blank=True, null=True)
    layout_family = models.CharField(max_length=50)

    def __str__(self):
        return f"{self.category} {self.race_type} ({self.layout_family})"

class Team(models.Model):
    name = models.CharField(max_length=255, unique=True)
    
    def __str__(self):
        return self.name

class Rider(models.Model):
    name = models.CharField(max_length=255)
    gender = models.CharField(max_length=50, blank=True, null=True)
    dob = models.CharField(max_length=50, blank=True, null=True)
    
    class Meta:
        unique_together = ('name', 'dob')

    def __str__(self):
        return f"{self.name} ({self.dob})"

class Result(models.Model):
    race = models.ForeignKey(Race, on_delete=models.CASCADE, related_name='results')
    rider = models.ForeignKey(Rider, on_delete=models.CASCADE, related_name='results', null=True, blank=True)
    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name='results', null=True, blank=True)
    
    display_rank = models.CharField(max_length=50, blank=True, null=True)
    numeric_rank = models.IntegerField(blank=True, null=True)
    status = models.CharField(max_length=20, default='OK') # OK, DNF, DNS, ABD, DSQ, REL
    bib = models.CharField(max_length=50, blank=True, null=True)
    
    time_ms = models.IntegerField(blank=True, null=True)
    speed = models.CharField(max_length=50, blank=True, null=True) # Stored as string to capture "#DIV/0!" safely
    points = models.IntegerField(blank=True, null=True)
    
    raw_row = models.JSONField(default=dict)
    needs_review = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.race} - Rank {self.display_rank} - {self.bib}"

class TeamMember(models.Model):
    result = models.ForeignKey(Result, on_delete=models.CASCADE, related_name='members')
    rider = models.ForeignKey(Rider, on_delete=models.CASCADE, related_name='team_entries')
    is_reserve = models.BooleanField(default=False)
    
    def __str__(self):
        return f"{self.rider.name} ({'Reserve' if self.is_reserve else 'Starter'}) - {self.result.team.name}"

class PointsDetail(models.Model):
    result = models.ForeignKey(Result, on_delete=models.CASCADE, related_name='points_details')
    sprint_number = models.IntegerField(null=True, blank=True) # Or sub-race identifier for Omnium
    lap_difference = models.IntegerField(default=0) # Lap +/-
    finish_order = models.IntegerField(null=True, blank=True)
    points_awarded = models.IntegerField(default=0)
    sub_scores_json = models.JSONField(default=dict) # Stores individual event scores for Omnium/Madison

    def __str__(self):
        return f"Result {self.result.id} - Sprint/Event {self.sprint_number}: {self.points_awarded} pts"
