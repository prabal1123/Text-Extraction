import os
from django.core.management.base import BaseCommand
from results.models import Championship, Communique, Race
from pipeline.segmenter import segment_pdf
from pipeline.classifier import classify_communique

class Command(BaseCommand):
    help = 'Segments and classifies PDF communiques for 2023 and 2025 championships.'

    def add_arguments(self, parser):
        parser.add_argument('--edition', type=int, nargs='*',
                            help='Edition numbers to classify (default: 75 77)')
        parser.add_argument('--all', action='store_true',
                            help='Classify every championship with a cached PDF')

    def handle(self, *args, **options):
        # Target only the 2023 (75th) and 2025 (77th) editions for Phase 2
        if options.get('all'):
            championships = Championship.objects.all().order_by('edition')
        else:
            championships = Championship.objects.filter(
                edition__in=options.get('edition') or [75, 77]).order_by('edition')
        
        for champ in championships:
            self.stdout.write(self.style.SUCCESS(f"\nProcessing {champ.edition}th Edition ({champ.year})..."))
            pdf_path = f".cache/pdfs/{champ.pdf_hash}.pdf"
            
            if not os.path.exists(pdf_path):
                self.stdout.write(self.style.ERROR(f"File not found: {pdf_path}. Run fetch_results first."))
                continue

            # Clear old classified data for this championship to allow re-runs
            Communique.objects.filter(championship=champ).delete()
            
            segmented_data = segment_pdf(pdf_path)
            
            for comm_data in segmented_data:
                header_text = comm_data['header_text']
                classification = classify_communique(header_text)
                
                # Assign number fallback from classified data
                comm_data['number'] = classification['number']
                
                pages_str = "-".join(map(str, comm_data['pages'])) if len(comm_data['pages']) > 1 else str(comm_data['pages'][0])
                
                comm_obj = Communique.objects.create(
                    championship=champ,
                    number=classification['number'],
                    page_range=pages_str,
                    race_date=classification['race_date'],
                    raw_header_text=header_text
                )
                
                Race.objects.create(
                    communique=comm_obj,
                    race_type=classification['race_type'],
                    category=classification['category'],
                    age_group=classification['age_group'],
                    gender=classification['gender'],
                    stage=classification['stage'],
                    distance=classification['distance'],
                    layout_family=classification['layout_family']
                )
                
                race_str = f"{classification['category']} {classification['race_type']}"
                self.stdout.write(f"  -> Comm {classification['number'] or 'None'} (Pg {pages_str}): {race_str} | Layout: {classification['layout_family']}")

        self.stdout.write(self.style.SUCCESS("\nPhase 2 Classification Complete!"))
