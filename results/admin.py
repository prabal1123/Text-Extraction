from django.contrib import admin
from .models import Championship, Communique, Race, Rider, Team, Result, TeamMember, PointsDetail

class RaceInline(admin.TabularInline):
    model = Race
    extra = 0

@admin.register(Communique)
class CommuniqueAdmin(admin.ModelAdmin):
    list_display = ('number', 'championship', 'page_range', 'race_date')
    list_filter = ('championship',)
    search_fields = ('number', 'raw_header_text')
    inlines = [RaceInline]

class ResultInline(admin.TabularInline):
    model = Result
    extra = 0
    fields = ('display_rank', 'bib', 'rider', 'team', 'status', 'time_ms', 'needs_review')
    readonly_fields = ('rider', 'team', 'bib', 'display_rank')

@admin.register(Race)
class RaceAdmin(admin.ModelAdmin):
    list_display = ('communique', 'category', 'race_type', 'stage', 'layout_family')
    list_filter = ('layout_family', 'gender', 'age_group', 'communique__championship')
    search_fields = ('race_type', 'category', 'communique__number')

@admin.register(Championship)
class ChampionshipAdmin(admin.ModelAdmin):
    list_display = ('edition', 'year', 'venue', 'source_url', 'created_at')
    search_fields = ('edition', 'year', 'venue')

@admin.register(Rider)
class RiderAdmin(admin.ModelAdmin):
    list_display = ('name', 'gender', 'dob')
    search_fields = ('name',)
    list_filter = ('gender',)

@admin.register(Team)
class TeamAdmin(admin.ModelAdmin):
    list_display = ('name',)
    search_fields = ('name',)

class TeamMemberInline(admin.TabularInline):
    model = TeamMember
    extra = 0

class PointsDetailInline(admin.TabularInline):
    model = PointsDetail
    extra = 0

@admin.register(Result)
class ResultAdmin(admin.ModelAdmin):
    list_display = ('race', 'display_rank', 'bib', 'rider', 'team', 'status', 'time_ms', 'needs_review')
    list_filter = ('needs_review', 'status', 'race__layout_family', 'race__communique__championship')
    search_fields = ('bib', 'rider__name', 'team__name', 'race__race_type')
    inlines = [TeamMemberInline, PointsDetailInline]
    actions = ['mark_as_reviewed']

    @admin.action(description='Clear needs_review flag for selected results')
    def mark_as_reviewed(self, request, queryset):
        queryset.update(needs_review=False)
        self.message_user(request, f"Successfully cleared review flag for {queryset.count()} results.")

@admin.register(TeamMember)
class TeamMemberAdmin(admin.ModelAdmin):
    list_display = ('rider', 'result', 'is_reserve')
    list_filter = ('is_reserve',)
    search_fields = ('rider__name', 'result__team__name')

@admin.register(PointsDetail)
class PointsDetailAdmin(admin.ModelAdmin):
    list_display = ('result', 'sprint_number', 'points_awarded', 'lap_difference')
    list_filter = ('sprint_number',)
