"""One-off seed builder for 5 High Courts (Allahabad, Bombay, Calcutta,
Madras, Karnataka).

Source: https://en.wikipedia.org/wiki/List_of_sitting_judges_of_the_high_courts_of_India
fetched via WebFetch on 2026-04-27. Names extracted manually below
(WebFetch summarizes large pages; pasting here keeps the seed
verifiable + reproducible).

Builds apps/api/src/caseops_api/scripts/seed_data/<court_id>_sitting_judges.json
in the same shape as delhi-hc_sitting_judges.json:
  {name, profile_url, date_of_birth, date_of_appointment_court, slug, bio_text}

Minimum-viable seed: just `name` + auto-derived `slug`. Other fields
left null / empty. The seed_hc_judges loader handles nulls gracefully.

Run:
  python scripts/one-off/build-hc-judge-seeds.py
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

# Per-HC raw judge name lists (without "Justice"/honorific). Union of
# Permanent + Additional judges as listed on Wikipedia. Some entries
# may be cross-listed (e.g. Vibhu Bakhru appears in Karnataka per
# Wikipedia but is widely known as a Delhi HC judge — Wikipedia may
# reflect a recent transfer). We trust the source; the resolver fails
# closed if a name doesn't actually belong to the court being matched.

HC_JUDGES: dict[str, list[str]] = {
    "allahabad-hc": [
        "Arun Bhansali", "Mahesh Chandra Tripathi", "Arindam Sinha",
        "Rajan Roy", "Yashwant Varma", "Atul Sreedharan",
        "Tirath Singh Thakur", "Siddhartha Varma", "Sangeeta Chandra",
        "Saumitra Dayal Singh", "Shekhar B. Saraf", "Salil Kumar Rai",
        "Rajesh Singh Chauhan", "Irshad Ali", "Saral Srivastava",
        "Jahangir Jamshed Munir", "Rajiv Gupta", "Siddharth", "Ajit Kumar",
        "Rajnish Kumar", "Abdul Moin", "Rajeev Misra", "Chandra Dhari Singh",
        "Ajay Bhanot", "Neeraj Tiwari", "Manoj Bajaj", "Prakash Padia",
        "Alok Mathur", "Pankaj Bhatia", "Saurabh Lavania", "Vivek Varma",
        "Piyush Agrawal", "Saurabh Shyam Shamsherry", "Jaspreet Singh",
        "Rajeev Singh", "Manju Rani Chauhan", "Karunesh Singh Pawar",
        "Yogendra Kumar Srivastava", "Manish Mathur", "Rohit Ranjan Agarwal",
        "Rajbeer Singh", "Deepak Verma", "Gautam Chowdhary",
        "Dinesh Pathak", "Manish Kumar", "Samit Gopal", "Sanjay Kumar Pachori",
        "Subhash Chandra Sharma", "Chandra Kumar Rai", "Krishan Pahal",
        "Sameer Jain", "Ashutosh Srivastava", "Subhash Vidyarthi",
        "Brij Raj Singh", "Shree Prakash Singh", "Vikas Budhwar",
        "Vikram D Chauhan", "Saurabh Srivastava", "Ram Manohar Narayan Mishra",
        "Syed Qamar Hasan Rizvi", "Manish Kumar Nigam", "Anish Kumar Gupta",
        "Nand Prabha Shukla", "Kshitij Shailendra", "Vinod Diwakar",
        "Prashant Kumar", "Manjive Shukla", "Arun Kumar Singh Deshwal",
        "Praveen Kumar Giri", "Jitendra Kumar Sinha", "Anil Kumar",
        "Sandeep Jain", "Avnish Saxena", "Madan Pal Singh", "Harvir Singh",
        "Pramod Kumar Srivastava", "Abdul Shahid", "Santosh Rai",
        "Tej Pratap Tiwari", "Zafeer Ahmad", "Arun Kumar",
        "Amitabh Kumar Rai", "Rajiv Lochan Shukla", "Vivek Saran",
        "Vivek Kumar Singh", "Garima Prashad", "Sudhanshu Chauhan",
        "Abdhesh Kumar Chaudhary", "Swarupama Chaturvedi", "Siddharth Nandan",
        "Kunal Ravi Singh", "Indrajeet Shukla", "Satya Veer Singh",
        "Ajay Kumar", "Chawan Prakash", "Divesh Chandra Samant",
        "Prashant Mishra", "Tarun Saxena", "Rajeev Bharti",
        "Padam Narayan Mishra", "Lakshmi Kant Shukla", "Jai Prakash Tiwari",
        "Devendra Singh", "Sanjiv Kumar", "Vani Ranjan Agrawal",
        "Achal Sachdev", "Babita Rani", "Vinai Kumar Dwivedi",
        "Jai Krishna Upadhyay",
    ],
    "bombay-hc": [
        "Shree Chandrashekhar", "Ravindra Vithalrao Ghuge",
        "Ajey Shrikant Gadkari", "Girish Sharadchandra Kulkarni",
        "Burgess Pesi Colabawalla", "Suman Shyam", "Makarand Subhash Karnik",
        "Bharati Harish Dangre", "Sarang Vijaykumar Kotwal",
        "Riyaz Iqbal Chagla", "Manish Pitale", "Vibha Vasant Kankanwadi",
        "Shriram Madhusudan Modak", "Nijamoddin Jahiroddin Jamadar",
        "Nitin Bhagawantrao Suryawanshi", "Anil Satyavijay Kilor",
        "Milind Narendra Jadhav", "Mukulika Shrikant Jawalkar",
        "Nitin Rudrasen Borkar", "Madhav Jayajirao Jamdar",
        "Amit Bhalchandra Borkar", "Abhay Ahuja", "Shivkumar Ganpatrao Dige",
        "Anil Laxman Pansare", "Sandipkumar Chandrabhan More",
        "Urmila Sachin Joshi-Phalke", "Kishore Chandrakant Sant",
        "Valmiki SA Menezes", "Kamal Rashmi Khata",
        "Sharmila Uttamrao Deshmukh", "Arun Ramnath Pedneker",
        "Sandeep Vishnupant Marne", "Gauri Vinod Godse",
        "Rajesh Shantaram Patil", "Arif Saleh Doctor",
        "Sanjay Anandrao Deshmukh", "Yanshivraj Gopichand Khobragade",
        "Mahendra Wadhumal Chandwani", "Abhay Sopanrao Waghwase",
        "Ravindra Madhusudan Joshi", "Vrushali Vijay Joshi",
        "Santosh Govindrao Chapalgaonkar", "Milind Manohar Sathaye",
        "Neela Kedar Gokhale", "Shailesh Pramod Brahme",
        "Firdosh Phiroze Pooniwalla", "Jitendra Shantilal Jain",
        "Abhay Jainarayanji Mantri", "Shyam Chhaganlal Chandak",
        "Neeraj Pradeep Dhote", "Somasekhar Sundaresan",
        "Manjusha Ajay Deshpande", "Nivedita Prakash Mehta",
        "Prafulla Surendrakumar Khubalkar", "Ashwin Damodar Bhobe",
        "Rohit Wasudeo Joshi", "Advait Mahendra Sethna",
        "Pravin Sheshrao Patil", "Sachin Shivajirao Deshmukh",
        "Gautam Ashwin Ankhad", "Mahendra Madhavrao Nerlikar",
        "Ajit Bhagwanrao Kadethankar", "Sushil Manohar Ghodeswar",
        "Aarti Arun Sathe", "Siddheshwar Sundarrao Thombre",
        "Mehroz Ashraf Khan Pathan", "Ranjitsinha Raja Bhonsale",
        "Nandesh Shankarrao Deshpande", "Amit Satyavan Jamsandekar",
        "Ashish Sahadev Chavan", "Sandesh Dadasaheb Patil",
        "Vaishali Nimbajirao Patil-Jadhav", "Abasaheb Dharmaji Shinde",
        "Shreeram Vinayak Shirsat", "Hiten Shamrao Venegavkar",
        "Farhan Parvez Dubash", "Rajnish Ratnakar Vyas",
        "Raj Damodar Wakode",
    ],
    "calcutta-hc": [
        "Sujoy Paul", "Tapabrata Chakraborty", "Arijit Banerjee",
        "Debangsu Basak", "Madhuresh Prasad", "Rajasekhar Mantha",
        "Sabyasachi Bhattacharyya", "Rajarshi Bharadwaj", "Shampa Sarkar",
        "Ravi Krishan Kapur", "Arindam Mukherjee", "Amrita Sinha",
        "Jay Sen Gupta", "Suvra Ghosh", "Tirthankar Ghosh",
        "Hiranmay Bhattacharyya", "Saugata Bhattacharyya", "Kausik Chanda",
        "Aniruddha Roy", "Sugato Majumdar", "Bivas Pattanayak",
        "Krishna Rao", "Ajoy Kumar Mukherjee", "Dinesh Kumar Sharma",
        "Gaurang Kanth", "Ananya Bandyopadhyay", "Rai Chattopadhyay",
        "Shampa Dutt", "Raja Basu Chowdhury", "Partha Sarathi Sen",
        "Apurba Sinha Ray", "Biswaroop Chowdhury", "Prasenjit Biswas",
        "Uday Kumar", "Ajay Kumar Gupta", "Supratim Bhattacharya",
        "Partha Sarathi Chatterjee", "Md. Shabbar Rashidi",
        "Chaitali Chatterjee", "Smita Das De", "Reetobroto Kumar Mitra",
        "Om Narayan Rai",
    ],
    "karnataka-hc": [
        "Vibhu Bakhru", "Anu Sivaraman", "Jayant Banerji",
        "Dinesh Kumar Singh", "Shankar Ganapathi Pandit",
        "Ramakrishna Devdas", "Bhotanhosur Mallikarjuna Shyam Prasad",
        "Siddappa Sunil Dutt Yadav", "Mohammad Nawaz",
        "Harekoppa Thimmanna Gowda Narendra Prasad",
        "Hethur Puttaswamygowda Sandesh",
        "Singapuram Raghavachar Krishna Kumar",
        "Ashok Subhashchandra Kinagi", "Suraj Govindaraj",
        "Sachin Shankar Magadum", "Jyoti Mulimani", "Nataraj Rangaswamy",
        "Pradeep Singh Yerur", "Maheshan Nagaprasan",
        "Maralur Indrakumar Arun", "Engalaguppe Seetharamaiah Indiresh",
        "Ravi Venkappa Hosmani", "Savanur Vishwajith Shetty",
        "Lalitha Kanneganti", "Shivashankar Amarannavar",
        "Vedavyasachar Srishananda", "Hanchate Sanjeev Kumar",
        "Mohammed Ghouse Shukure Kamal", "Perugu Sree Sudha",
        "Chillakur Sumalatha", "Anant Ramanath Hegde", "Siddaiah Rachaiah",
        "Kannakuzhyil Sreedharan Hemalekha", "Kumbhajadala Manmadha Rao",
        "Tara Vitasta Ganju", "Cheppudira Monappa Poonacha",
        "Gurusiddaiah Basavaraja", "Venkatesh Naik Thavaryanaik",
        "Vijaykumar Adagouda Patil", "Rajesh Rai Kallangala",
        "Kurubarahalli Venkataramareddy Aravind",
        "Taj Ali Moulasab Nadaf", "Geetha Kadaba Bharatharaja Setty",
        "Borkatte Muralidhara Pai", "Tyagaraja Narayan Inavally",
    ],
    "madras-hc": [
        "Sushrut Arvind Dharmadhikari", "R. Suresh Kumar",
        "S. M. Subramaniam", "Anita Sumanth", "P. Velmurugan",
        "G. Jayachandran", "C. V. Karthikeyan", "N. Sathish Kumar",
        "A. D. Jagadish Chandira", "G. R. Swaminathan", "Abdul Quddhose",
        "M. Dhandapani", "Pondicherry Daivasigamani Audikesavalu",
        "P. T. Asha", "N. Nirmal Kumar", "N. Anand Venkatesh",
        "G. K. Ilanthiraiyan", "Krishnan Ramasmy", "C. Saravanan",
        "B. Pugalendhi", "Senthilkumar Ramamoorthy",
        "Tadakamalla Vinod Kumar", "Hemant Chandangoudar", "Shamim Ahmed",
        "Murali Shankar Kuppuraju", "Thamilselvi T. Valayapalayam",
        "Sundaram Srimathy", "D. Bharatha Chakravarthy", "R. Vijayakumar",
        "Mohammed Shaffiq", "Mummineni Sudheer Kumar", "Kasoju Surendhar",
        "Nidumolu Mala", "S. Sounthar", "Sunder Mohan",
        "Kabali Kumaresh Babu", "Lekshmana Chandra Victoria Gowri",
        "Pillaipakkam Bahukutumbi Balaji",
        "Kandhasami Kulandaivelu Ramakrishnan", "Ramachandran Kalaimathi",
        "K. Govindarajan Thilakavadi", "Venkatachari Lakshminarayanan",
        "Periyasamy Vadamalai", "Ramasamy Sakthivel", "P. Dhanabal",
        "Chinnasamy Kumarappan", "Kandasamy Rajasekar", "N. Senthilkumar",
        "G. Arul Murugan", "R. Poornima", "M. Jothiraman",
        "Augustine Devadoss Maria Clete",
    ],
}


def slugify(name: str) -> str:
    """Lowercase + hyphenate + strip non-alphanumeric. Mirrors the
    delhi-hc seed convention (e.g. 'Pratibha M. Singh' →
    'justice-pratibha-m-singh')."""
    s = re.sub(r"[^a-zA-Z0-9 ]+", "", name).strip().lower()
    s = re.sub(r"\s+", "-", s)
    return f"justice-{s}"


def build_entry(name: str) -> dict:
    return {
        "name": f"Justice {name}",
        "profile_url": None,
        "date_of_birth": None,
        "date_of_appointment_court": None,
        "slug": slugify(name),
        "bio_text": None,
    }


def main() -> int:
    seed_dir = Path(__file__).resolve().parents[2] / "apps" / "api" / "src" / "caseops_api" / "scripts" / "seed_data"
    if not seed_dir.exists():
        print(f"ERROR: seed dir missing: {seed_dir}", file=sys.stderr)
        return 1
    sys.stdout.reconfigure(encoding="utf-8")
    for court_id, names in HC_JUDGES.items():
        out_path = seed_dir / f"{court_id}_sitting_judges.json"
        # De-dupe within the court (the source has a few legitimate
        # duplicates due to Permanent vs Additional sections).
        seen = set()
        unique_names = []
        for n in names:
            n_norm = n.strip()
            if n_norm not in seen:
                seen.add(n_norm)
                unique_names.append(n_norm)
        entries = [build_entry(n) for n in unique_names]
        out_path.write_text(
            json.dumps(entries, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        print(f"  {court_id}: wrote {len(entries)} entries → {out_path.name}")
    print(f"DONE: {len(HC_JUDGES)} HC seed files written.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
