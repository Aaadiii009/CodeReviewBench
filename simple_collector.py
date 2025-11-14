"""
GitHub PR Data Collector - WORKING VERSION
Collects BOTH inline comments AND general reviews
"""

from github import Github, Auth, GithubException
from config import GITHUB_TOKEN
import json
import time
from datetime import datetime, timedelta
import os


class SimpleGitHubCollector:
    """Collects PR data from GitHub repositories"""

    def __init__(self):
        """Initialize GitHub connection"""
        print("Connecting to GitHub...")
        auth = Auth.Token(GITHUB_TOKEN)
        self.github = Github(auth=auth)
        print("✓ Connected!\n")

    def _print_rate_limit(self):
        """Safely print rate-limit info"""
        try:
            rate_limit = self.github.get_rate_limit()
            resources = getattr(rate_limit, "resources", None)
            core = None
            if isinstance(resources, dict):
                core = resources.get("core")
            else:
                core = getattr(resources, "core", None)

            if core:
                print(f"  ✓ API calls remaining: {core.remaining}/{core.limit}")
        except Exception:
            pass

    def collect_from_repo(self, owner, repo_name, max_prs=15):
        """Collect PRs from a single repository"""
        print(f"📦 Collecting from {owner}/{repo_name}...")
        print("-" * 60)

        try:
            repo = self.github.get_repo(f"{owner}/{repo_name}")
            print(f"  ✓ Found repository: {repo.full_name}")
            print(f"  ✓ Stars: {repo.stargazers_count}")
            self._print_rate_limit()

            # IMPORTANT: Get ALL closed PRs, not just merged
            # We'll check merged status later
            pulls = repo.get_pulls(state="closed", sort="updated", direction="desc")

            collected_prs = []
            processed = 0
            skipped_reasons = {
                'not_merged': 0,
                'no_reviews': 0,
                'too_large': 0,
                'too_old': 0,
                'too_small': 0,
                'error': 0
            }

            print(f"\n  Searching for PRs with reviews...")

            for pr in pulls:
                if len(collected_prs) >= max_prs:
                    break

                processed += 1
                
                if processed % 15 == 0:
                    print(f"  📊 Progress: checked {processed}, found {len(collected_prs)}")
                    print(f"     Rejected: not_merged={skipped_reasons['not_merged']}, "
                          f"no_reviews={skipped_reasons['no_reviews']}, "
                          f"size={skipped_reasons['too_small'] + skipped_reasons['too_large']}")

                # Check if PR is suitable
                is_suitable, reason = self.is_suitable_pr(pr)
                if not is_suitable:
                    skipped_reasons[reason] += 1
                    continue

                # Extract PR data (this also gets reviews)
                pr_data = self.extract_pr_data(pr, owner, repo_name)
                if pr_data and len(pr_data['human_reviews']) > 0:
                    collected_prs.append(pr_data)
                    loc = pr_data['metadata']['loc_added'] + pr_data['metadata']['loc_deleted']
                    comments = len(pr_data['human_reviews'])
                    print(f"  ✅ PR #{pr.number}: {pr.title[:35]}... "
                          f"({loc} LOC, {comments} reviews)")
                else:
                    skipped_reasons['no_reviews'] += 1

                time.sleep(0.2)

                # Stop after reasonable attempts
                if processed >= 100:
                    print(f"  ⚠ Checked 100 PRs, moving to next repo...")
                    break

            print(f"\n✓ Collected {len(collected_prs)} PRs from {owner}/{repo_name}")
            if len(collected_prs) == 0:
                print(f"  ℹ️  Rejection reasons:")
                for reason, count in skipped_reasons.items():
                    if count > 0:
                        print(f"     - {reason}: {count}")
            print("=" * 60)
            print()

            return collected_prs

        except GithubException as e:
            print(f"  ✗ GitHub Error: {e}")
            return []
        except Exception as e:
            print(f"  ✗ Unexpected error: {e}")
            return []

    def is_suitable_pr(self, pr):
        """
        Check if PR meets basic criteria (before fetching reviews)
        Returns: (bool, reason_string)
        """
        try:
            # 1. Must be MERGED
            if not pr.merged:
                return False, 'not_merged'
            
            # 2. Check size (10 to 2000 lines)
            total_changes = pr.additions + pr.deletions
            if total_changes < 10:
                return False, 'too_small'
            if total_changes > 2000:
                return False, 'too_large'
            
            # 3. Must be recent (last 3 years)
            cutoff_date = datetime.now() - timedelta(days=1095)
            pr_date = pr.created_at.replace(tzinfo=None) if pr.created_at.tzinfo else pr.created_at
            if pr_date < cutoff_date:
                return False, 'too_old'

            # Don't check comments here - we'll check after extracting
            return True, 'suitable'
            
        except Exception as e:
            return False, 'error'

    def extract_pr_data(self, pr, owner, repo_name):
        """
        Extract data from a PR - INCLUDING BOTH INLINE COMMENTS AND GENERAL REVIEWS
        """
        try:
            pr_data = {
                "pr_id": f"{owner}/{repo_name}#{pr.number}",
                "repository": f"{owner}/{repo_name}",
                "pr_number": pr.number,
                "title": pr.title,
                "description": pr.body if pr.body else "",
                "author": pr.user.login,
                "created_at": pr.created_at.isoformat(),
                "merged_at": pr.merged_at.isoformat() if pr.merged_at else "",
                "url": pr.html_url,
                "files_changed": [],
                "human_reviews": [],
                "metadata": {
                    "loc_added": pr.additions,
                    "loc_deleted": pr.deletions,
                    "num_files": pr.changed_files,
                    "num_review_comments": 0,  # Will update this
                    "labels": [label.name for label in pr.labels],
                },
            }

            # GET INLINE REVIEW COMMENTS (file-specific comments)
            try:
                inline_comments = list(pr.get_review_comments()[:30])
                for comment in inline_comments:
                    pr_data["human_reviews"].append({
                        "reviewer": comment.user.login,
                        "timestamp": comment.created_at.isoformat(),
                        "file": comment.path,
                        "line_number": comment.line or 0,
                        "content": comment.body,
                        "type": "inline",
                    })
            except Exception:
                pass

            # GET GENERAL REVIEWS (approve/reject/comment reviews)
            # THIS IS WHAT WAS MISSING!
            try:
                reviews = list(pr.get_reviews())
                for review in reviews:
                    # Only include reviews with actual text content
                    if review.body and len(review.body.strip()) > 10:
                        pr_data["human_reviews"].append({
                            "reviewer": review.user.login,
                            "timestamp": review.submitted_at.isoformat() if review.submitted_at else "",
                            "content": review.body,
                            "state": review.state,  # APPROVED, CHANGES_REQUESTED, COMMENTED
                            "type": "general",
                        })
            except Exception:
                pass

            # Update comment count
            pr_data["metadata"]["num_review_comments"] = len(pr_data["human_reviews"])

            return pr_data
            
        except Exception as e:
            print(f"    ✗ Error extracting PR #{pr.number}: {e}")
            return None


def main():
    """Main function to run the collector"""
    print("=" * 70)
    print("  🚀 GitHub PR Data Collector - WORKING VERSION")
    print("=" * 70)
    print()
    print("📋 What this collects:")
    print("  • Merged pull requests (quality assured)")
    print("  • Both inline comments AND general reviews")
    print("  • PRs with 10-2000 lines changed")
    print("  • From last 3 years")
    print()

    try:
        collector = SimpleGitHubCollector()
    except Exception as e:
        print(f"✗ Failed to initialize: {e}")
        return

    # Better repository selection - known for good code reviews
    repositories = [
        {"owner": "fastapi", "repo": "fastapi"},        # Modern, good reviews
        {"owner": "pallets", "repo": "flask"},          # Established, good reviews  
        {"owner": "django", "repo": "django"},          # Large, active reviews
        {"owner": "microsoft", "repo": "playwright-python"},  # Well-reviewed
        {"owner": "tiangolo", "repo": "sqlmodel"},      # Newer, active reviews
    ]

    all_data = []
    repos_tried = 0

    for repo_config in repositories:
        repos_tried += 1
        print(f"🔄 Repository {repos_tried}/{len(repositories)}")
        
        prs = collector.collect_from_repo(
            repo_config["owner"], 
            repo_config["repo"], 
            max_prs=10  # Try to get 10 per repo
        )
        
        all_data.extend(prs)
        print(f"📊 Running total: {len(all_data)} PRs collected\n")
        
        # Stop early if we have enough
        if len(all_data) >= 35:
            print("✅ Collected enough data (35+ PRs)!\n")
            break

    # Save results
    if all_data:
        print("\n💾 Saving data...")
        os.makedirs("data", exist_ok=True)
        output_file = "data/collected_prs.json"
        
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(all_data, f, indent=2, ensure_ascii=False)

        # Calculate statistics
        total_comments = sum(len(pr['human_reviews']) for pr in all_data)
        avg_comments = total_comments / len(all_data)
        total_loc = sum(pr['metadata']['loc_added'] + pr['metadata']['loc_deleted'] 
                       for pr in all_data)
        avg_loc = total_loc / len(all_data)
        
        # Count inline vs general reviews
        inline_count = sum(1 for pr in all_data for r in pr['human_reviews'] if r['type'] == 'inline')
        general_count = sum(1 for pr in all_data for r in pr['human_reviews'] if r['type'] == 'general')
        
        print(f"✓ Saved {len(all_data)} PRs to {output_file}")
        print("\n" + "=" * 70)
        print("🎉 DATA COLLECTION SUCCESSFUL!")
        print("=" * 70)
        print(f"📊 DATASET STATISTICS:")
        print(f"   Total PRs:              {len(all_data)}")
        print(f"   Repositories:           {len(set(pr['repository'] for pr in all_data))}")
        print(f"   Total reviews:          {total_comments}")
        print(f"   - Inline comments:      {inline_count}")
        print(f"   - General reviews:      {general_count}")
        print(f"   Avg reviews per PR:     {avg_comments:.1f}")
        print(f"   Total lines changed:    {total_loc:,}")
        print(f"   Avg LOC per PR:         {avg_loc:.0f}")
        print(f"   Output file:            {output_file}")
        print("=" * 70)
        print()
        print("✨ Next step: Run 'python analyze_data.py' to create visualizations!")
        print("=" * 70)
        
    else:
        print("\n" + "=" * 70)
        print("❌ NO DATA COLLECTED")
        print("=" * 70)
        print("\n🔍 Troubleshooting:")
        print("   1. Check your internet connection")
        print("   2. Verify GitHub token: python test_connection.py")
        print("   3. Check rate limit (you might need to wait)")
        print("   4. Try with just one repository first")
        print("=" * 70)


if __name__ == "__main__":
    main()