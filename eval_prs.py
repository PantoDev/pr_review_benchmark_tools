import csv
import json
import signal
import time
from datetime import datetime
from pathlib import Path

from dateutil import parser
from jinja2 import Template
from openai import OpenAI

from config import GEMINI_BASE_URL, GEMINI_TOKEN, IS_GEMINI, OPENAI_TOKEN


class QualityChecker:

    def __init__(self, input_file: str, output_file: str):
        self.input_file = input_file
        self.output_file = output_file
        self.processed_rows: set[int] = set()
        self.load_processed_rows()
        self.running = True
        self.last_request_time = 0.0
        self.openai = OpenAI(
            api_key=GEMINI_TOKEN,
            base_url=GEMINI_BASE_URL) if IS_GEMINI else OpenAI(
                api_key=OPENAI_TOKEN)
        self.model = "gemini-2.0-flash" if IS_GEMINI else "o3-mini"
        self.min_request_interval = 3  # Minimum seconds between requests

    def signal_handler(self, signum, frame):
        print("\nGracefully shutting down...")
        self.running = False

    def load_processed_rows(self):
        """Load already processed row numbers from output file"""
        if Path(self.output_file).exists():
            with open(self.output_file, newline='') as f:
                reader = csv.DictReader(f)
                self.processed_rows = {
                    int(row['row_number'])
                    for row in reader if 'row_number' in row
                }

    def ask_for_date_range(self) -> tuple:
        """Get date range from user input"""
        while True:
            try:
                start_date = input("Enter start date (YYYY-MM-DD): ")
                end_date = input("Enter end date (YYYY-MM-DD): ")
                start = datetime.strptime(start_date, "%Y-%m-%d")
                end = datetime.strptime(end_date, "%Y-%m-%d")
                return start, end
            except ValueError:
                print("Invalid date format. Please use YYYY-MM-DD")

    def ask_for_batch_size(self) -> int:
        """Get batch size from user input"""
        while True:
            try:
                batch_size = input("Enter batch size: ")
                return int(batch_size)
            except ValueError:
                print("Invalid batch size. Please enter a number")

    def get_rows(self) -> list[dict]:
        """Filter rows based on date range"""
        filtered_rows = []
        with open(self.input_file, newline='') as f:
            reader = csv.DictReader(f)
            for idx, row in enumerate(reader):
                try:
                    # Parse the complex timestamp format
                    row_datetime = parser.parse(row['Date'])
                    # Compare only the date parts
                    row_datetime.date()
                    row['original_row_number'] = idx
                    filtered_rows.append(row)
                except (ValueError, TypeError) as e:
                    print(f"Skipping row with invalid date:"
                          f"{row['Date']}, Error: {e}")
        return filtered_rows

    def wait_for_rate_limit(self):
        """Ensure minimum time between API calls"""
        current_time = time.time()
        time_since_last_request = current_time - self.last_request_time

        if time_since_last_request < self.min_request_interval:
            sleep_time = self.min_request_interval - time_since_last_request
            print(f"Rate limiting: waiting {sleep_time:.1f} seconds...")
            time.sleep(sleep_time)

        self.last_request_time = time.time()

    def rate_suggestions_batch(self, data: list[dict]) -> list[dict]:
        """Rate multiple suggestions using GPT-4 with rate limiting"""

        self.wait_for_rate_limit()

        render_args = {
            'suggestions': [{
                'id': i,
                'suggestion': d['Suggestion'],
                'code_diff': d['Small Diff'],
            } for i, d in enumerate(data)],
        }

        final_results: list[dict] = []
        for i, _ in enumerate(data):
            final_results.append({
                'id': i,
                'category': None,
                'is_false_positive': None
            })

        with open('prompts/categorization_system.jinja') as f0:
            category_system_template = Template(f0.read().strip())
            category_system_prompt = category_system_template.render(
                render_args)

        with open('prompts/categorization_user.jinja') as f1:
            category_user_template = Template(f1.read().strip())
            category_user_prompt = category_user_template.render(render_args)
        txn_id = str(time.time())

        category_results = self._call_llm(
            txn_id=txn_id,
            system_prompt=category_system_prompt,
            user_prompt=category_user_prompt,
        )
        category_results_map = {r['id']: r for r in category_results}

        for f in final_results:
            _id = f['id']
            if _id in category_results_map:
                f['category'] = category_results_map[_id]['category']
            else:
                f['category'] = "-1"
                print(f"{id} not in category_results_map")

        with open('prompts/false_positive_system.jinja') as f2:
            false_positive_system_template = Template(f2.read().strip())
            false_positive_system_prompt = false_positive_system_template \
                .render(render_args)

        with open('prompts/false_positive_user.jinja') as f3:
            false_positive_user_template = Template(f3.read().strip())
            false_positive_user_prompt = false_positive_user_template.render(
                render_args)
        txn_id = str(time.time())
        false_positive_results = self._call_llm(
            txn_id=txn_id,
            system_prompt=false_positive_system_prompt,
            user_prompt=false_positive_user_prompt,
        )
        false_positive_results_map = {
            r['id']: r
            for r in false_positive_results
        }

        for f in final_results:
            _id = f['id']
            if _id in false_positive_results_map:
                f['is_false_positive'] = false_positive_results_map[_id][
                    'is_false_positive']
            else:
                f['is_false_positive'] = False
                print(f"{id} not in false_positive_results_map")

        print("Final results: " + str(final_results))

        return final_results

    def _call_llm(self, txn_id: str, system_prompt: str,
                  user_prompt: str) -> dict:
        with open(f'llmlogs/{txn_id}.txt', 'a') as f:
            f.write(f"System:\n{system_prompt}\n\nUser:\n{user_prompt}")
            msgs = [{
                "role": "system",
                "content": system_prompt
            }, {
                "role": "user",
                "content": user_prompt
            }]
            response = self.openai.chat.completions.create(
                model=self.model,
                messages=msgs,
            )

            result_text = response.choices[0].message.content

            if result_text.startswith("```"):
                result_text = result_text[3:-3].strip()
            if result_text.startswith("json"):
                result_text = result_text[4:].strip()
            f.write(f"\n\nAnswer:\n{result_text}")
            results = json.loads(result_text)

        return results

    def process_rows(self, filtered_rows: list[dict], batch_size: int):
        """Process filtered rows and write results"""
        if not filtered_rows:
            print("No rows to process")
            return

        # Calculate total number of batches
        total_unprocessed = sum(
            1 for row in filtered_rows
            if int(row['original_row_number']) not in self.processed_rows)
        total_batches = (total_unprocessed + batch_size - 1) // batch_size
        current_batch_no = 0

        print(f"Found {len(filtered_rows)} rows"
              f" to process ({total_unprocessed} unprocessed)")
        proceed = input("Proceed with processing? (y/n): ").lower()
        if proceed != 'y':
            return

        # Setup signal handler for graceful shutdown
        signal.signal(signal.SIGINT, self.signal_handler)

        # Maintain fixed column order
        # input_fieldnames = next(csv.reader(open(self.input_file)))
        # Update line 178 in process_rows:
        with open(self.input_file, newline='') as infile:
            input_fieldnames = next(csv.reader(infile))
        output_fieldnames = input_fieldnames + [
            'results', "is_false_positive", "final_result", 'row_number'
        ]

        file_exists = Path(self.output_file).exists()

        with open(self.output_file, 'a', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=output_fieldnames)
            if not file_exists:
                writer.writeheader()

            current_batch = []
            current_rows = []

            for row in filtered_rows:
                if not self.running:
                    break

                original_row_num = int(row['original_row_number'])
                if original_row_num in self.processed_rows:
                    continue

                current_batch.append(row)
                current_rows.append(row)

                if len(current_batch
                       ) >= batch_size or row == filtered_rows[-1]:
                    current_batch_no += 1
                    print(
                        f"Processing batch {current_batch_no}/{total_batches} "
                        f"({len(current_batch)} suggestions)...")
                    results = self.rate_suggestions_batch(current_batch)
                    assert len(results) == len(
                        current_batch), "Invalid results length"

                    # Write results for the batch
                    for row_data, result in zip(current_rows, results):
                        output_row = {
                            k: v
                            for k, v in row_data.items()
                            if k != 'original_row_number'
                        }
                        output_row['results'] = result.get('category')
                        output_row['is_false_positive'] = result.get(
                            'is_false_positive')
                        output_row[
                            'final_result'] = "FALSE_POSITIVE" if result.get(
                                'is_false_positive') else result.get(
                                    'category')
                        output_row['row_number'] = row_data[
                            'original_row_number']
                        writer.writerow(output_row)
                        self.processed_rows.add(
                            int(row_data['original_row_number']))

                    f.flush()
                    current_batch = []
                    current_rows = []


def quality_analysis(input_file: str):
    output_file = f"{input_file.strip('.csv')}.output.csv"
    processor = QualityChecker(input_file, output_file)
    batch_size = processor.ask_for_batch_size()
    rows = processor.get_rows()
    processor.process_rows(rows, batch_size)


if __name__ == '__main__':
    input_file = input("Enter the input CSV file path: ")
    if not Path(input_file).exists():
        print("File does not exist. Please check the path.")
        exit(1)
    if not input_file.endswith('.csv'):
        print("Please provide a CSV file.")
        exit(1)
    # Perform quality analysis
    quality_analysis(input_file)
