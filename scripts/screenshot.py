"""
Screenshot of the running app -> docs/screenshot.png

Opens the app, runs a backtest with the form's defaults (Moving Average
Crossover, Conservative against the unmanaged baseline, AAPL/AMZN/GOOGL/JPM/MSFT,
2023), waits for the results and saves the top of the page. The data is the
synthetic sample file, and the page says so in its banner.

Not part of requirements.txt; install once:

    pip install playwright && python -m playwright install chromium

Then, with the app running on a fresh database (`make dev` or `make run`):

    python -m scripts.screenshot --url http://localhost:8000
"""
import argparse
from pathlib import Path

from playwright.sync_api import sync_playwright

REPO_ROOT = Path(__file__).resolve().parent.parent


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0].strip())
    parser.add_argument('--url', default='http://localhost:8000')
    parser.add_argument('--output', default=str(REPO_ROOT / 'docs' / 'screenshot.png'))
    parser.add_argument('--width', type=int, default=1280)
    parser.add_argument('--height', type=int, default=1370)
    args = parser.parse_args()

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={'width': args.width, 'height': args.height},
                                device_scale_factor=2)
        page.goto(args.url)
        page.get_by_role('button', name='Run backtest').click()
        page.get_by_text('vs baseline #').first.wait_for(timeout=120_000)
        page.mouse.move(0, 0)  # off the button, so it isn't captured in its hover state
        page.evaluate('window.scrollTo(0, 0)')
        page.wait_for_timeout(500)
        page.screenshot(path=args.output)
        browser.close()
    print(f'Wrote {args.output}')


if __name__ == '__main__':
    main()
