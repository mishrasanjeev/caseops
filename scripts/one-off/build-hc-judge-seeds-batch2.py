"""Batch 2 of HC judge seeds — covers the 17 HCs not in batch 1.

Source: en.wikipedia.org/wiki/List_of_sitting_judges_of_the_high_courts_of_India
fetched via WebFetch on 2026-04-27 in 3 calls (mass-fetch truncates).

Builds seed_data/<court_id>_sitting_judges.json for each, in the same
shape as delhi-hc seed.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

HC_JUDGES: dict[str, list[str]] = {
    "andhra-pradesh-hc": [
        "Lisa Gill", "Cheekati Manavendranath Roy", "Ravi Nath Tilhari",
        "Rao Raghunandan Rao", "Battu Devanand", "Donadi Ramesh",
        "Nainala Jayasurya", "Boppudi Krishna Mohan",
        "Kanchireddy Suresh Reddy", "Boddupalli Sri Bhanumathi",
        "Konakanti Sreenivasa Reddy", "Gannamaneni Ramakrishna Prasad",
        "Venkateswarlu Nimmagadda", "Tarlada Rajasekhar Rao",
        "Satti Subba Reddy", "Ravi Cheemalapati", "Vaddiboyana Sujatha",
        "Subhendu Samanta",
        "Boppana Varaha Lakshmi Narasimha Chakravarthi",
        "Venkata Jyothirmai Pratapa", "Venuthurmalli Gopala Krishna Rao",
        "Harinath Nunepally", "Kiranmayee Mandava", "Sumathi Jagadam",
        "Nyapathy Vijay", "Maheswara Rao Kuncheam",
        "Thoota Chandra Dhana Sekar", "Challa Gunaranjan",
        "Avadhanam Hari Haranadha Sarma", "Yadavalli Lakshmana Rao",
        "Tuhin Kumar Gedela", "Balaji Medamalli",
    ],
    "chhattisgarh-hc": [
        "Ramesh Sinha", "Sanjay Kumar Agrawal", "Sanjay Agrawal",
        "Parth Prateem Sahu", "Rajani Dubey", "Narendra Kumar Vyas",
        "Naresh Kumar Chandravanshi", "Sachin Singh Rajput",
        "Rakesh Mohan Pandey", "Radhakishan Agrawal", "Sanjay Kumar Jaiswal",
        "Ravindra Kumar Agrawal", "Bibhu Datta Guru",
        "Amitendra Kishore Prasad",
    ],
    "gujarat-hc": [
        "Sunita Agarwal", "Alpesh Yeshwant Kogje",
        "Arvindsingh Ishwarsingh Supehia", "Bhargav Dhirenbhai Karia",
        "Sangeeta Kamalsingh Vishen",
        "Neranahalli Srinivasan Sanjay Gowda", "Ilesh Jashvantrai Vora",
        "Gita Gopi", "Vaibhavi Devang Nanavati",
        "Nirzarkumar Sushilkumar Desai", "Nikhil Shreedharan Kariel",
        "Samir Jyotindraprasad Dave", "Hemant Maheshchandra Prachchhak",
        "Aniruddha Pradyumna Mayee", "Niral Rashmikant Mehta",
        "Nisha Mahendrabhai Thakore", "Susan Valentine Pinto",
        "Hasmukhbhai Dalsukhbhai Suthar", "Jitendra Champaklal Doshi",
        "Mangesh Rameshchandra Mengdey", "Divyeshkumar Amrutlal Joshi",
        "Devan Mahendrabhai Desai", "Moxa Kiran Thakker",
        "Vimal Kanaiyalal Vyas", "Pranav Shailesh Trivedi",
        "Sanjeev Jayendra Thaker", "Deeptendra Narayan Ray",
        "Maulik Jitendra Shelat", "Liyakathussain Shamsuddin Pirzada",
        "Ramchandra Thakurdas Vachhani", "Jayesh Lakhanshibhai Odedra",
        "Pranav Maheshbhai Raval", "Mool Chand Tyagi",
        "Dipak Mansukhlal Vyas", "Utkarsh Thakorbhai Desai",
    ],
    "himachal-hc": [
        "Gurmeet Singh Sandhawalia", "Vivek Singh Thakur", "Ajay Mohan Goel",
        "Sandeep Sharma", "Jyotsna Rewal Dua", "Sushil Kukreja",
        "Virender Singh", "Ranjan Sharma", "Bipin Chander Negi",
        "Rakesh Kainthla", "Jiya Lal Bhardwaj", "Romesh Verma",
    ],
    "jammu-kashmir-hc": [
        "Arun Palli", "Sanjeev Kumar", "Sindhu Sharma", "Rajnesh Oswal",
        "Sanjay Dhar", "Mohd. Akram Chowdhary", "Rahul Bharti",
        "Moksha Khajuria Kazmi", "Wasim Sadiq Nargal", "Rajesh Sekhri",
        "Mohd. Yousuf Wani", "Sanjay Parihar", "Shahzad Azeem",
    ],
    "jharkhand-hc": [
        "Mahesh Sharadchandra Sonak", "Sujit Narayan Prasad",
        "Rongon Mukhopadhyay", "Ananda Sen", "Rajesh Shankar",
        "Anil Kumar Choudhary", "Rajesh Kumar", "Anubha Rawat Choudhary",
        "Sanjay Kumar Dwivedi", "Deepak Roshan", "Sanjay Prasad",
        "Pradeep Kumar Srivastava", "Arun Kumar Rai",
    ],
    "kerala-hc": [
        "Soumen Sen", "Ala Kunnil Jayasankaran Nambiar",
        "Anil Kolavampara Narendran", "Raja Vijayaraghavan Valsala",
        "J. Nisha Banu", "Sathish Ninan", "Devan Ramachandran",
        "Krishnan Natarajan", "Conrad Stansilaus Dias",
        "Pulleri Vadhyarillath Kunhikrishnan",
        "Thirumuppath Raghavan Ravi", "Bechu Kurian Thomas",
        "Gopinath Puzhankara", "Murali Purushothaman", "Karunakaran Babu",
        "Kauser Edappagath", "Abdul Rahim Musaliar Badharudeen",
        "Viju Abraham", "Mohammed Nias Chovvakkaran Puthiyapurayil",
        "Basant Balaji", "Chandrasekharan Kartha Jayachandran",
        "Shoba Annamma Eapen", "Johnson John", "Gopinathan Unnithan Girish",
        "Chellappan Nadar Pratheep Kumar",
        "Mullappally Abdul Aziz Abdul Hakhim",
        "Syam Kumar Vadakke Mudavakkat", "Harisankar Vijayan Menon",
        "Manu Sreedharan Nair", "Easwaran Subramani",
        "Manoj Pulamby Madhavan", "Marakkaparambil Bhargavan Snehalatha",
        "Parameswara Panicker Krishna Kumar",
        "Kodassery Veliyath Madom Jayakumar",
        "Muralee Krishna Shankaramoole", "Jobin Sebastian",
        "Pandikkaran Varadaraja Iyer Balakrishnan",
        "Preeta Arvindan Krishnamma",
    ],
    "madhya-pradesh-hc": [
        "Sanjeev Sachdeva", "Vivek Rusia", "Anand Pathak", "Vivek Agarwal",
        "Vijay Kumar Shukla", "Gurpal Singh Ahluwalia", "Subodh Abhyankar",
        "Vivek Kumar Singh", "Vishal Dhagat", "Vishal Mishra",
        "Pranay Verma", "Sandeep Natvarlal Bhatt", "Maninder Singh Bhatti",
        "Dwarka Dhish Bansal", "Milind Ramesh Phadke", "Anuradha Shukla",
        "Sanjeev Sudhakar Kalgaonkar", "Hirdesh", "Avanindra Kumar Singh",
        "Vinay Saraf", "Vivek Jain", "Rajendra Kumar Vani",
        "Pramod Kumar Agarwal", "Binod Kumar Dwivedi", "Devnarayan Mishra",
        "Gajendra Singh", "Ashish Shroti", "Deepak Khot", "Amit Seth",
        "Pavan Kumar Dwivedi", "Pushpendra Yadav", "Anand Singh Bahrawat",
        "Ajay Kumar Nirankari", "Jay Kumar Pillai", "Himanshu Joshi",
        "Ramkumar Choubey", "Rajesh Kumar Gupta", "Alok Awasthi",
        "Ratnesh Chandra Singh Bisen", "Bhagwati Prasad Sharma",
        "Pradeep Mittal",
    ],
    "manipur-hc": [
        "M. Sundar",
    ],
    "meghalaya-hc": [
        "Revati Prashant Mohite Dere",
    ],
    "orissa-hc": [
        "Harish Tandon", "Akshaya Kumar Mishra", "Biswajit Mohanty",
        "Sanjib Banerjee", "Arindam Dasgupta", "Bidyut Ranjan Sarangi",
        "Sushanta Kumar Mishra", "Rabindra Kumar Parida", "Sangita Sharma",
        "Priyabrata Dash", "Ajit Kumar Sahoo", "Suvadip Dash",
        "Subhakanta Panda", "Raghunath Biswal", "Sumit Agarwal",
        "Saurav Dutt Rath", "Nikhil Pandey", "Rabindra Maharathy",
        "Manoranjan Dash", "Hari Prasanna Mahapatra", "Santi Ranjan Parida",
        "Bhagirathi Devi Singh", "Tushar Ranjan Dash", "Subit Raut",
        "Deepa Mohanty", "Rachakonda Srinivas", "Vinay Varma",
        "Mahendra Nath Pal",
    ],
    "patna-hc": [
        "Janardan Prasad Singh", "Sandeep Madan", "Ahsanuddin",
        "Shwetank Kumar", "Rakesh Kumar", "Aparesh Kumar Singh",
        "Shailendra Kumar", "Avinash Kumar Singh", "Sanjay Kumar",
        "Prithviraj Singh", "Ashutosh Kumar", "Sudhir Singh",
        "Ajay Kumar Mishra", "Hemant Srivastava", "Vikram Kumar Singh",
        "Vidya Prakash Dubey", "Virat Chandra Singh", "Sanjay",
        "Suman Lata Singh", "Nidhi Prasad", "Murugan", "Ajay Singh",
        "Anuradha Singh", "Sheo Kumar Singh", "Pratima Singh",
        "Abhijeet Kumar", "Krishnadayal Singh", "Ravi Ranjan Kumar",
        "Arun Kumar Singh", "Raj Kamal Singh", "Ritesh Kumar Shukla",
        "Manorama Singh", "Anup Kumar Singh", "Priya Prakash",
        "Shailendra Yadav", "Sunil Kumar Singh", "Mukhtar Ahmad",
        "Prabhaker Yadav", "Prem Narayan Singh",
    ],
    "punjab-hc": [
        "Gurmeet Singh Sandhawalia", "Jasgurpreet Singh Puri",
        "Deepak Nehra", "Ritu Bahri", "Virinder Singh",
        "Harinder Singh Sidhu", "Rajesh Sharma", "Harpreet Kaur Kochhar",
        "Jitendra Kumar Malik", "Anita Chaudhry", "Aman Inder Singh",
        "Mahfooz Ahmad Syed", "Harinder Singh", "Harmanpreet Singh",
        "Vikas Bahl", "Sanjay Goel", "Sushil Kumar Garg", "Puneet Jain",
        "Mridula Kalia", "Arun Palli", "Subodh Sharma",
        "Gurpinder Singh", "Hemant Gupta", "Harmanpreet Kaur",
        "Ratan Chaudhry", "Vikram Nath", "Baldevbir Singh",
        "Navdeep Singh", "Sandeep S. Sandhu", "Harinder Kaur Grewal",
        "Harkesh Malik", "Sanjay Vashisth", "Vinod Sharma",
        "Arun Chowdhary", "Harshvardhan Singh Bhati", "Sukhraj Singh",
        "Shamita Mukherjee", "Tariq Husain", "Chandrashekhar Bhardwaj",
        "Sangeeta Chaudhry", "Sanjeev Jain", "Suresh Babu P.",
        "Priyanka", "Prashant", "Meenu Bhardwaj", "Anoop Chitkara",
    ],
    "rajasthan-hc": [
        "Dinesh Mehta", "Satish Chandra Sharma", "Ramendra Jain",
        "Prakash Gupta", "Hari Shankar", "Geeta Goyal",
        "Mahesh Chand Sharma", "Samir Jain", "Radhakrishnan V.",
        "Sameer Jain", "Mayank Baranwal", "Mahendra Singh Yadav",
        "Govind Raj Ramdal", "Manish Chand Katara", "Arun Kumar Verma",
        "Rajeev Kedia", "Arun Choudhry", "Rashid Akhtar",
        "Brijesh Dhanaskar", "Salim Akhtar", "Priya Sharma",
        "Devendra Singh", "Saurabh Bhatt", "Rajesh Dadu",
        "Vinita Choudhry", "Jaspal Singh", "Dinesh Chand",
        "Virendra Kumar Rao", "Aaditya Singh", "Rahul Bhargava",
        "Govind Prasad Singh", "Umesh Chandra Sharma", "Dipak Sharma",
        "Brijraj Sharma", "Anil Yadav",
    ],
    "sikkim-hc": [
        "Muhamed Mustaque Ayumantakath", "Hari Prasanna Mahapatra",
        "Biswajit Mohanty",
    ],
    "tripura-hc": [
        "Arunava Sinha", "Abhijit Gangopadhyay", "Manojit Mandal",
        "Ritwik Banerjee", "Subrata Bhattacharya",
    ],
    "uttarakhand-hc": [
        "Manoj Kumar Gupta", "Ritu Bahri", "Pradeep Pant", "Rajeev Mehta",
        "Arun Kumar", "Ravindra Singh Rawat", "Sanjeev Prasad Yadav",
        "Alok Mishra", "Balendu Pratap Singh", "Jainendra Singh",
    ],
}


def slugify(name: str) -> str:
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
    sys.stdout.reconfigure(encoding="utf-8")
    total = 0
    for court_id, names in HC_JUDGES.items():
        seen = set()
        unique_names = []
        for n in names:
            n_norm = n.strip()
            if n_norm not in seen:
                seen.add(n_norm)
                unique_names.append(n_norm)
        entries = [build_entry(n) for n in unique_names]
        out_path = seed_dir / f"{court_id}_sitting_judges.json"
        out_path.write_text(
            json.dumps(entries, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        total += len(entries)
        print(f"  {court_id}: wrote {len(entries)} entries")
    print(f"DONE: {len(HC_JUDGES)} HC seed files, {total} judges total.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
